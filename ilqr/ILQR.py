import jax.numpy as np
from jax import grad, jacfwd, jacrev, random, jit
from tqdm.notebook import trange, tqdm


class ILQR:
    def __init__(self, final_cost, running_cost, model, u_range, horizon, per_iter, model_der=None):
        '''
            final_cost:     v(x)    ->  cost, float
            running_cost:   l(x, u) ->  cost, float
            model:          f(x, u) ->  new state, [n_x]
        '''
        self.f = model
        self.v = final_cost
        self.l = running_cost

        self.u_range = u_range
        self.horizon = horizon
        self.per_iter = per_iter

        # specify derivatives
        self.l_x = grad(self.l, 0)
        self.l_u = grad(self.l, 1)
        self.l_xx = jacfwd(self.l_x, 0)
        self.l_uu = jacfwd(self.l_u, 1)
        self.l_ux = jacrev(self.l_u, 0)

        self.v_x = jacrev(self.v)
        self.v_xx = jacfwd(self.v_x)

        if model_der == None:
            self.f_x = jacrev(self.f, 0)
            self.f_u = jacfwd(self.f, 1)

            (self.f, self.f_u, self.f_x,) = [jit(e)
                                             for e in [self.f, self.f_u, self.f_x, ]]
        else:
            # using provided function for step
            self.f_x = model_der['f_x']
            self.f_u = model_der['f_u']

        # speed up
        (self.l, self.l_u, self.l_uu, self.l_ux, self.l_x, self.l_xx,
         self.v, self.v_x, self.v_xx) = \
            [jit(e) for e in [self.l, self.l_u, self.l_uu, self.l_ux, self.l_x, self.l_xx,
                              self.v, self.v_x, self.v_xx]]

    def cal_K(self, x_seq, u_seq):
        '''
            Calculate all the necessary derivatives, and compute the Ks
        '''
        state_dim = x_seq[0].shape[-1]
#         v_seq = [None] * self.horizon
        v_x_seq = [None] * self.horizon
        v_xx_seq = [None] * self.horizon

        last_x = x_seq[-1]
#         v_seq[-1] = self.v(last_x)
        v_x_seq[-1] = self.v_x(last_x)
        v_xx_seq[-1] = self.v_xx(last_x)

        k_seq = [None] * self.horizon
        kk_seq = [None] * self.horizon

        for i in tqdm(range(self.horizon - 2, -1, -1), desc='backward', leave=False):
            x, u = x_seq[i], u_seq[i]

            # get all grads
            lx = self.l_x(x, u)
            lu = self.l_u(x, u)
            lxx = self.l_xx(x, u)
            luu = self.l_uu(x, u)
            lux = self.l_ux(x, u)

            fx = self.f_x(x, u)
            fu = self.f_u(x, u)
#             fxx = self.f_xx(x, u)
#             fuu = self.f_uu(x, u)
#             fux = self.f_ux(x, u)

            vx = v_x_seq[i+1]
            vxx = v_xx_seq[i+1]

            # cal Qs
            q_x = lx + fx.T @ vx
            q_u = lu + fu.T @ vx
            q_xx = lxx + fx.T @ vxx @ fx
            q_uu = luu + fu.T @ vxx @ fu
            q_ux = lux + fu.T @ vxx @ fx
#             q_xx = lxx + fx.T @ vxx @ fx + vx @ fxx
#             q_uu = luu + fu.T @ vxx @ fu + (fuu.T @ vx).T
#             q_ux = lux + fu.T @ vxx @ fx + (fux.T @ vx).T

            # cal Ks
            inv_quu = np.linalg.inv(q_uu)

            k = - inv_quu @ q_u
            kk = - inv_quu @ q_ux

            # if i == 0:
            # names = ['k', 'kk', 'inv_qq', 'lx', 'lu', 'lxx', 'luu', 'lux',
            #          'fx', 'fu', 'vx', 'vxx', 'qx', 'qu', 'qxx', 'quu', 'qux']
            # Ms = [k, kk, inv_quu, lx, lu, lxx, luu, lux,
            #       fx, fu, vx, vxx, q_x, q_u, q_xx, q_uu, q_ux]

            # print(f"\n\n-------------ITER {i}------------------------------")
            # for n, m in zip(names, Ms):
            #     print(f"{n}\n\t{np.max(m)}\n")

#             print(f"INVQUU:\n\t {inv_quu}")
#             print(f"QU:\n\t {inv_quu}")
#             print(f"k:\n\t {k}\n\n\n")

            # cal Vs
            new_v = q_u @ k / 2
            new_vx = q_x + q_u @ kk
            new_vxx = q_xx + q_ux.T @ kk

            # record
            k_seq[i] = k
            kk_seq[i] = kk
            v_x_seq[i] = new_vx
            v_xx_seq[i] = new_vxx

        return k_seq, kk_seq

    def forward(self, x_seq, u_seq, k_seq, kk_seq):
        new_x_seq = [None] * self.horizon
        new_u_seq = [None] * self.horizon

        new_x_seq[0] = x_seq[0]  # copy

        for i in trange(self.horizon - 1, desc='forward', leave=False):
            x = new_x_seq[i]

            new_u = u_seq[i] + k_seq[i] + kk_seq[i] @ (x - x_seq[i])
            new_x = self.f(x, new_u)

            new_u_seq[i] = new_u
            new_x_seq[i+1] = new_x

        return new_x_seq, new_u_seq

    def predict(self, x_seq, u_seq):
        for _ in trange(self.per_iter, desc='ILQR', leave=False):
            k_seq, kk_seq = self.cal_K(x_seq, u_seq)

            x_seq, u_seq = self.forward(x_seq, u_seq, k_seq, kk_seq)

        u_seq[-1] = u_seq[-2]  # filling
        return np.array(x_seq), np.array(u_seq)
