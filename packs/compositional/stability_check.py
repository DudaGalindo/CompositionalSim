import numpy as np
from ..directories import data_loaded
from . import equation_of_state
from ..utils import constants as ctes
import time

## Encontrar os pontos estacionarios. Estes correspondem aos pontos nos quais a derivada de g com respeito a Y é 0
## Todas as equações foram confirmadas pelo livro do Dandekar e a biblioteca do thermo
# ph=0 - vapor. ph=1 - liquid.

class StabilityCheck:

    """ Check for stability of a thermodynamic equilibrium and returns the
    equilibrium phase compositions (perform the flash calculation) """
    # IMPROVE AND ORGANIZE BETTER THE CONSTANT K PART

    def __init__(self, P, T):
        # this is called once
        P = np.copy(P)
        self.EOS = ctes.EOS_class(T) #só para os casos isotérmicos - non isothermal entrariam em run (eu acho)
        self.ph_L = np.ones(len(P), dtype = bool)
        self.ph_V = np.zeros(len(P), dtype = bool)
        self.T = T
        self.constant_K = data_loaded['compositional_data']['component_data']['constant_K']
        if self.constant_K:
            self.K = np.array(data_loaded['compositional_data']['component_data']['K'])[:,np.newaxis]
        else: self.K = self.equilibrium_ratio_Wilson(P)
        self.x = np.empty([ctes.Nc, len(P)])
        self.y = np.empty_like(self.x)
        self.L = np.empty(len(P))
        self.V = np.empty(len(P))

    def run_init(self, P, z, pflash = True, ponteiro_flash = []):
        #self.K = self.equilibrium_ratio_Wilson(P)
        P = np.copy(P)
        if np.sum(pflash,dtype=bool)==True:
            ponteiro_flash = np.ones(len(P), dtype = bool)
            '-------------------- Get new time-step parameters --------------------'
        self.P = P
        self.z = np.copy(z)
        #ponteiro_flash[np.sum(self.z==0, dtype=bool)] = True
        #import pdb; pdb.set_trace()
        #ponteiro_nc1 = np.zeros_like(ponteiro_flash_aux)
        #ponteiro_nc1[]
        self.z[self.z<=0] = 1e-30

        if not pflash and any(~ponteiro_flash) and ctes.Nc>1:
            #self.z[self.z==0] = 1e-30
            sp1, sp2 = self.StabilityTest(np.copy(~ponteiro_flash))
            ponteiro_aux = ponteiro_flash[~ponteiro_flash]
            #self.K[~ponteiro_flash] = Ksp1[(np.round(sp1,14) > 1)] + Ksp2[(np.round(sp2,14) > 1)]
            ponteiro_aux[(np.round(sp1,14) > 1) + (np.round(sp2,14) > 1)] = True #os que devem passar para o calculo de flash
            ponteiro_flash[~ponteiro_flash] = ponteiro_aux

        #self.molar_properties(np.ones_like(ponteiro_flash,dtype=bool))
        #self.check_phase_nc_1()

        if ctes.Nc==1:
            ksi_L, ksi_V, rho_L, rho_V = self.check_phase_nc_1()
        else: ksi_L, ksi_V, rho_L, rho_V = self.molar_properties(np.copy(ponteiro_flash)) #perform the actual flash
        #ksi_L, ksi_V, rho_L, rho_V = self.update_EOS_dependent_properties()
        return self.L, self.V, self.x, self.y, ksi_L, ksi_V, rho_L, rho_V

    def run(self, P, z, wells):
        ponteiro_flash = self.skip_phase_stability_test(P, z)
        #ponteiro_flash = np.ones(len(P), dtype = bool)
        self.use_previous_K(P, z, ponteiro_flash)
        #ponteiro_flash[wells['all_wells']] = True
        #ponteiro_flash[((self.V==0) + (self.L==0))*(P > self.P)] = False
        self.L, self.V, self.x, self.y, ksi_L, ksi_V, rho_L, rho_V = self.run_init(P, z, False, ponteiro_flash)
        return self.L, self.V, self.x, self.y, ksi_L, ksi_V, rho_L, rho_V

    def check_phase_nc_1(self):
        Pv = self.vapor_pressure_pure_substancies()
        Pv = Pv[:,np.newaxis] * np.ones_like(self.z)
        self.x = self.z
        self.y = self.z

        self.L[self.P > Pv[self.z==1]] = 1
        self.L[self.P < Pv[self.z==1]] = 0.

        self.V = 1. - self.L
        self.K = self.y/self.x
        self.K[self.x==0] = 1

        lnphil, Zl = self.lnphi_Z_based_on_deltaG(self.x, self.P, self.ph_L)
        lnphiv, Zv = self.lnphi_Z_based_on_deltaG(self.y, self.P, self.ph_V)
        ksi_L, ksi_V, rho_L, rho_V = self.update_EOS_dependent_properties(Zl, Zv)
        return ksi_L, ksi_V, rho_L, rho_V

    def use_previous_K(self, P_new, z_new, ponteiro_flash):
        'Reference: Rezaveisi dissertation'
        'Two conditions are used here:\
        1) checks if exists a physically meaningfull solution of the  RR \
        equation:'
        ponteiro_K = np.zeros(len(ponteiro_flash),dtype=bool)
        cond1 = np.sum(z_new[:,ponteiro_flash] * self.K[:,ponteiro_flash],axis = 0)
        cond2 = np.sum(z_new[:,ponteiro_flash] / self.K[:,ponteiro_flash], axis = 0)
        ponteiro_K_aux = ponteiro_K[ponteiro_flash]
        ponteiro_K_aux[(cond1 >= 1) * (cond2 >= 1)] = True
        ponteiro_K[ponteiro_flash] = ponteiro_K_aux
        #ponteiro_K[(self.K==1).sum(axis=0,dtype=bool)] = False
        self.K[:,~ponteiro_K] = self.equilibrium_ratio_Wilson(P_new[~ponteiro_K])
        #self.K[:,:] = self.equilibrium_ratio_Wilson(P_new[:])
        #if any((self.K==1).sum(axis=0,dtype=bool)): import pdb; pdb.set_trace()

    def skip_phase_stability_test(self, P_new, z_new):
        'Two conditions are used here:\
        2) Check if the Gibbs free energy of the K^n TWO PHASE mixture is less than the \
        mixture with the global composition z^(n+1))'
        z_new[z_new==0] = 1e-30
        ponteiro_flash = np.ones(len(P_new), dtype = bool)
        #dP_bigg_or_equal = (P_new>self.P) + (abs(P_new - self.P)<1)
        ponteiro_flash[((self.V==0) + (self.L==0))] = False
        #ponteiro_flash[wells['all_wells']] = False
        lj = np.empty([1, 2, len(ponteiro_flash[ponteiro_flash])])
        xij = np.empty([ctes.Nc, 2, len(ponteiro_flash[ponteiro_flash])])
        lnphi_ij = np.empty_like(xij)
        lj[0,0,:] = self.L[ponteiro_flash]
        lj[0,1,:] = self.V[ponteiro_flash]
        xij[:,0,:] = self.x[:,ponteiro_flash]
        xij[:,1,:] = self.y[:,ponteiro_flash]
        if any(ponteiro_flash):
            lnphiy = self.EOS.lnphi(self.y[:,ponteiro_flash], P_new[ponteiro_flash], self.ph_V[ponteiro_flash])
            lnphix = self.EOS.lnphi(self.x[:,ponteiro_flash], P_new[ponteiro_flash], self.ph_L[ponteiro_flash])
            lnphiz = self.EOS.lnphi(z_new[:,ponteiro_flash], P_new[ponteiro_flash], self.ph_L[ponteiro_flash])
            lnphi_ij[:,0,:] = lnphix
            lnphi_ij[:,1,:] = lnphiy
            xij[xij==0] = 1e-30
            #logxij = np.log(xij)
            #logxij[xij==0] = 0
            c1 = np.sum(np.sum(lj * xij * (np.log(xij) + lnphi_ij),axis = 0), axis = 0)
            c2 = np.sum(z_new[:,ponteiro_flash] * (np.log(z_new[:,ponteiro_flash]) + lnphiz), axis = 0)
            ponteiro_flash_aux = ponteiro_flash[ponteiro_flash]
            ponteiro_flash_aux[c1 <= c2] = True
            ponteiro_flash[ponteiro_flash] = ponteiro_flash_aux
        return ponteiro_flash

    def skip_phase_equilibrium(self):
        pass

        "SECOND HEURISTIC METHOD FROM RESAVEISI"

    def vapor_pressure_pure_substancies(self):
        '''Lee-Kesler Correlation - only valid for T < Tc'''
        Tr = self.T/ctes.Tc
        A = 5.92714 - 6.09648 / Tr - 1.2886 * np.log(Tr) + 0.16934 * Tr**6
        B = 15.2518 - 15.6875 / Tr - 13.4721 * np.log(Tr) + 0.4357 * Tr**6
        Pv = ctes.Pc * np.exp(A + ctes.w * B)
        return Pv

    def equilibrium_ratio_Wilson(self, P):
        K = np.exp(5.37 * (1 + ctes.w) * (1 - 1/(self.T / ctes.Tc)))[:,np.newaxis] / \
                (P / ctes.Pc[:,np.newaxis])
        return K

    """------------------- Stability test calculation -----------------------"""

    def StabilityTest(self, ponteiro_stab_check):
        # I can still improve this (saving lines only)
        ''' In the lnphi function: 0 stands for vapor phase and 1 for liquid '''

    #****************************INITIAL GUESS******************************#
    ## Both approaches bellow should be used in case the phase is in the critical region

    #*****************************Test one**********************************#
        #Used alone when the phase investigated (z) is clearly vapor like (ph = 0)

        ponteiro = np.copy(ponteiro_stab_check)
        Y = np.empty(self.z.shape)
        lnphiz = np.empty(self.z.shape)
        Y[:,ponteiro] = self.z[:,ponteiro] /self.K[:,ponteiro]
        y = Y / np.sum(Y, axis = 0)[np.newaxis,:]
        lnphiz[:,ponteiro] = self.EOS.lnphi(self.z[:,ponteiro], self.P[ponteiro], self.ph_V[ponteiro])
        i=0
        while any(ponteiro):
            Y_old = np.copy(Y[:,ponteiro])
            lnphiy = self.EOS.lnphi(y[:,ponteiro], self.P[ponteiro], self.ph_L[ponteiro])
            if any(np.isnan(lnphiy).flatten()): import pdb; pdb.set_trace()
            Y[:,ponteiro] = np.exp(np.log(self.z[:,ponteiro]) + lnphiz[:,ponteiro] - lnphiy)
            y[:,ponteiro] = Y[:,ponteiro] / np.sum(Y[:,ponteiro], axis = 0)[np.newaxis,:]
            stop_criteria = np.max(abs(Y[:,ponteiro] / Y_old - 1), axis = 0)
            ponteiro_aux = ponteiro[ponteiro]
            ponteiro_aux[stop_criteria < 1e-9] = False
            ponteiro[ponteiro] = ponteiro_aux
            i+=1
            if i>100:
                print('SP1 loop')
                ponteiro[ponteiro] = False
        K_sp1 = (self.z/y)[:,ponteiro_stab_check]

        stationary_point1 = np.sum(Y[:,ponteiro_stab_check], axis = 0)

    #*****************************Test two**********************************#
        #Used alone when the phase investigated (z) is clearly liquid like (ph == 1)
        ponteiro = np.copy(ponteiro_stab_check)

        Y[:,ponteiro] = self.K[:,ponteiro] * self.z[:,ponteiro]
        y = Y / np.sum(Y, axis = 0)[np.newaxis,:]
        lnphiz[:,ponteiro] = self.EOS.lnphi(self.z[:,ponteiro], self.P[ponteiro], self.ph_L[ponteiro])
        i = 0
        while any(ponteiro):
            Y_old = np.copy(Y[:,ponteiro])
            lnphiy = self.EOS.lnphi(y[:,ponteiro], self.P[ponteiro], self.ph_V[ponteiro])
            if any(np.isnan(lnphiy).flatten()): import pdb; pdb.set_trace()
            Y[:,ponteiro] = np.exp(np.log(self.z[:,ponteiro]) + lnphiz[:,ponteiro] - lnphiy)
            y[:,ponteiro] = Y[:,ponteiro] / np.sum(Y[:,ponteiro], axis = 0)[np.newaxis,:]
            stop_criteria = np.max(abs(Y[:,ponteiro] / Y_old - 1), axis = 0)
            ponteiro_aux = ponteiro[ponteiro]
            ponteiro_aux[stop_criteria < 1e-9] = False
            ponteiro[ponteiro] = ponteiro_aux
            i+=1
            if i>100:
                print('SP2 loop')
                ponteiro[ponteiro] = False
        K_sp2 = (y/self.z)[:,ponteiro_stab_check]

        stationary_point2 = np.sum(Y[:,ponteiro_stab_check], axis = 0)

        K = self.K[:,ponteiro_stab_check]
        sp1 = abs(stationary_point1 - 1)
        sp2 = abs(stationary_point2 - 1)
        K[:,sp1>sp2] = K_sp1[:,sp1>sp2]
        K[:,sp2>sp1] = K_sp2[:,sp2>sp1]
        KWilson_criteria = np.zeros_like(self.P,dtype=bool)
        KWilson_criteria_aux = np.sum(abs(K-1)<1e-14,axis=0,dtype=bool)
        KWilson_criteria[ponteiro_stab_check] = KWilson_criteria_aux
        self.K[:,KWilson_criteria] = self.equilibrium_ratio_Wilson(self.P[KWilson_criteria])
        return stationary_point1, stationary_point2

    """-------------------- Biphasic flash calculations ---------------------"""

    def molar_properties(self, ponteiro):
        ksi_L, ksi_V, rho_L, rho_V = self.molar_properties_Whitson(ponteiro)
        #ksi_L, ksi_V, rho_L, rho_V = self.molar_properties_Yinghui(ponteiro)
        return ksi_L, ksi_V, rho_L, rho_V

    def lnphi_Z_based_on_deltaG(self, xkj, P, ph):
        lnphi, Z = self.EOS.lnphi_Z_deltaG(xkj, P, ph)

        # test phase ph is lnphi[...,0], the other phase is lnphi[...,1]
        deltaG_molar = np.sum(xkj * (lnphi[...,1] - lnphi[...,0]), axis = 0)

        dG_neg = deltaG_molar<0

        ph[dG_neg] = 1 - ph[dG_neg]

        lnphi_out = np.copy(lnphi[...,0])
        lnphi_out[:,dG_neg] = lnphi[:,dG_neg,1]
        Z_out = np.copy(Z[...,0])
        Z_out[dG_neg] = Z[dG_neg,1]
        return lnphi_out, Z_out

    def solve_objective_function_Yinghui(self, z1, zi, K1, KNc, Ki, K, x):
        x1_min = z1 * (1 - KNc) / (K1 - KNc)
        x1_max = (1 - KNc) / (K1 - KNc)
        K_equal_K1 = K==K1
        K_equal_KNc = K==KNc

        x1_max[abs(K1-KNc)<1e-15] = 1
        x1_min[abs(K1-KNc)<1e-15] = 0

        vols_zi_neg = np.zeros(len(K1), dtype = bool)
        vols_zi_neg[np.sum(zi < 0, axis = 0, dtype=bool)] = True
        KNc_z_neg = KNc[vols_zi_neg].ravel()
        K1_z_neg = K1[vols_zi_neg]
        z1_z_neg = z1[vols_zi_neg]
        zi_z_neg = zi[:,vols_zi_neg]
        Ki_z_neg = Ki[:,vols_zi_neg]
        vols_zi_neg_num = np.sum(vols_zi_neg*1) + 1 - np.sign(np.sum(vols_zi_neg*1))
        Ki_z_neg_K_big1 = Ki_z_neg[Ki_z_neg > 1]#.reshape(int(len(Ki_z_neg[Ki_z_neg>1])/vols_zi_neg_num), vols_zi_neg_num)
        theta = np.ones(zi[:,vols_zi_neg].shape)

        theta[Ki_z_neg > 1] = ((1 - KNc_z_neg) / (Ki_z_neg_K_big1 - KNc_z_neg))#.ravel()
        aux_eq = (Ki_z_neg - 1) * z1_z_neg[np.newaxis,:] / (zi_z_neg * (K1_z_neg[np.newaxis,:] - 1) /
                theta - (K1_z_neg[np.newaxis,:] - Ki_z_neg))

        #aux_eq = (K - 1) * z1 / (z * (K1 - 1) / theta - (K1 - K))
        cond = (Ki_z_neg - 1) * z1_z_neg[np.newaxis,:] / zi_z_neg
        cond[zi_z_neg == 0] = 0
        cond_aux = np.ones(cond.shape[1], dtype = bool)
        cond_aux[np.sum(cond <= 0, axis = 0, dtype=bool)] = False
        aux_eq_cond = aux_eq[:,cond_aux]
        vols_aux = len(cond_aux==True)

        vols_aux = np.sum(cond_aux*1) + 1 - np.sign(np.sum(cond_aux*1))
        aux_eq_cond = aux_eq_cond[aux_eq_cond >= 0].reshape(int(len(aux_eq_cond[aux_eq_cond >= 0])/vols_aux), vols_aux)
        x1_max_aux = np.copy(x1_max[vols_zi_neg])

        x1_max_aux[cond_aux] = np.min(aux_eq_cond, axis = 0, initial=0)
        x1_max[vols_zi_neg] = x1_max_aux

        x1_min_aux = np.copy(x1_min[vols_zi_neg])
        x1_min_aux[~cond_aux] = np.max(aux_eq[:,~cond_aux], axis = 0, initial=0)

        x1_min_aux[x1_min_aux < 0] = 0
        x1_min[vols_zi_neg] = x1_min_aux

        if any(x1_min > x1_max):
            raise ValueError('There is no physical root')

        x1 = ((x1_min + x1_max) / 2) #* (1 - np.sign(i))

        x1_new = np.copy(x1)
        ponteiro = np.ones(len(x1), dtype = bool)
        i=0
        ft1 = (K1 - KNc) / (KNc - 1)
        ft2 = ((Ki - KNc[np.newaxis,:]) /
            (KNc[np.newaxis,:] - 1)) * zi * \
            (K1[np.newaxis,:] - 1)
        ft3_1 = (Ki - 1) * z1[np.newaxis,:]
        ft3_2 = (K1[np.newaxis,:] - Ki)
        while any(ponteiro):
            i+=1
            x1[ponteiro] = np.copy(x1_new[ponteiro])
            ft3 = ft3_1[:,ponteiro] + ft3_2[:,ponteiro] * x1[ponteiro][np.newaxis,:]
            f = 1 + (ft1[ponteiro]) * x1[ponteiro] + np.sum(ft2[:,ponteiro] * x1[ponteiro][np.newaxis,:]
                / (ft3), axis = 0)
            df = (ft1[ponteiro]) + np.sum(ft2[:,ponteiro] * z1[ponteiro][np.newaxis,:] * (Ki[:,ponteiro] - 1) \
                / (ft3) ** 2, axis = 0)
            x1_new[ponteiro] = x1[ponteiro] - f/df #Newton-Raphson iterative method
            x1_aux = x1_new[ponteiro]
            x1_aux[x1_aux > x1_max] = (x1_min[x1_aux > x1_max] + x1_max[x1_aux > x1_max])/2
            x1_aux[x1_aux < x1_min] = (x1_min[x1_aux < x1_min] + x1_max[x1_aux < x1_min])/2
            x1_new[ponteiro] = x1_aux
            ponteiro_aux = ponteiro[ponteiro] #o que muda de tamanho
            ponteiro_aux[abs(f) < 1e-10] = False
            ponteiro[ponteiro] = ponteiro_aux
            x1_max = x1_max[ponteiro_aux]
            x1_min = x1_min[ponteiro_aux]
            x1_max[f[ponteiro_aux] * df[ponteiro_aux] > 0] = x1[ponteiro][f[ponteiro_aux] * df[ponteiro_aux] > 0]
            x1_min[f[ponteiro_aux] * df[ponteiro_aux] < 0] = x1[ponteiro][f[ponteiro_aux] * df[ponteiro_aux] < 0]
            if i > 300:
                #import pdb; pdb.set_trace()
                ponteiro[ponteiro] = False

        x1 = x1_new.copy()
        xi = (K1[np.newaxis,:] - 1) * zi * x1[np.newaxis,:] / (ft3_1 +
            ft3_2 * x1[np.newaxis,:])

        x_not_z1_zero = np.copy(x).T
        x_not_z1_zero[K_equal_K1.T] = x1.T
        x_not_z1_zero[K_equal_KNc.T] = (1 - np.sum(xi, axis = 0) - x1).T
        aux_xi = np.ones(x_not_z1_zero.shape,dtype=bool)
        aux_xi[K_equal_K1.T] = False
        aux_xi[K_equal_KNc.T] = False
        x_not_z1_zero[aux_xi] = xi.T.ravel()
        return x_not_z1_zero.T

    def Yinghui_method(self, ponteiro):

        """ Shaping K to Nc-2 components by removing K1 and KNc and z to Nc-2
        components by removing z1 and zNc """
        K = self.K[:,ponteiro]
        x = self.x[:,ponteiro]
        z = self.z[:,ponteiro]
        K1 = np.max(K, axis = 0); KNc = np.min(K, axis = 0)
        z1 = z.T[(K == K1[np.newaxis,:]).T].T

        aux = np.ones(K.shape, dtype = bool)
        self.K_equal_K1 = K == K1[np.newaxis,:]
        xs1 = self.K_equal_K1[:,self.K_equal_K1.sum(axis=0)>1]
        if any(xs1): xs1[xs1][0] = False
        self.K_equal_K1[:,self.K_equal_K1.sum(axis=0)>1] = xs1

        self.K_equal_KNc = K == KNc[np.newaxis,:]
        xs2 = self.K_equal_KNc[:,self.K_equal_KNc.sum(axis=0)>1]
        if any(xs2):
            xss2 = xs2[xs2]
            xss2[0] = False
            xs2[xs2]  = xss2
            #ver caso onde todo mundo é igual
        self.K_equal_KNc[:,self.K_equal_KNc.sum(axis=0)>1] = xs2
        aux[self.K_equal_K1] = False
        aux[self.K_equal_KNc] = False
        Ki = K.T[aux.T]
        zi = z.T[aux.T]

        ''' Reshaping them into the original matricial form '''
        vols_ponteiro = np.sum(ponteiro*1) + 1 - np.sign(np.sum(ponteiro*1))
        Ki = Ki.reshape(vols_ponteiro, int(len(Ki)/vols_ponteiro)).T
        zi = zi.reshape(vols_ponteiro, int(len(zi)/vols_ponteiro)).T

        #starting x

        """ Solution """
        if any(~(z1==0)):
            x[:,~(z1 == 0)] = self.solve_objective_function_Yinghui(z1[~(z1 == 0)], zi[:,~(z1 == 0)],
                                                K1[~(z1 == 0)], KNc[~(z1 == 0)], Ki[:,~(z1 == 0)],
                                                K[:,~(z1 == 0)], x[:,~(z1 == 0)])

        '''Explicit Calculation of xi'''
        #self.solve_objective_function_Yinghui_explicitly()
        z_z1_zero = z[:,z1==0]
        K_z1_zero = K[:,z1==0]
        K_KNc_z1_zero = K_z1_zero[K_z1_zero == KNc[z1==0][np.newaxis,:]]

        aux_xNc = np.zeros(K_z1_zero.shape, dtype = bool); aux_x1 = np.copy(aux_xNc)
        aux_xNc[K_z1_zero == KNc[z1==0][np.newaxis,:]] = True
        aux_x1[K_z1_zero == K1[z1==0][np.newaxis,:]] = True
        aux_xi = ~(aux_xNc + aux_x1)
        xi_z1_zero = ((K1[z1 == 0][np.newaxis,:] - 1) * zi[:,z1 == 0] / (K1[z1 == 0][np.newaxis,:] - Ki[:,z1 == 0]))
        x_z1_zero = np.zeros(x[:,z1 == 0].shape)
        x_z1_zero[aux_xNc] = (K1[z1 == 0] - 1) * z_z1_zero[aux_xNc] / (K1[z1 == 0] - K_z1_zero[aux_xNc])
        x_z1_zero[aux_xi] = xi_z1_zero.ravel()
        x_z1_zero[aux_x1] = 1 - np.sum(x_z1_zero, axis = 0)
        x[:,z1 == 0] = x_z1_zero
        self.x[:,ponteiro] = x
        self.y[:,ponteiro] = self.K[:,ponteiro] * self.x[:,ponteiro]

    def molar_properties_Yinghui(self, ponteiro):
        #razao = fl/fv -> an arbitrary vector to enter in the iterative mode

        razao = np.ones(self.z.shape)/2
        ponteiro_save = np.copy(ponteiro)
        i = 0
        #x1 = np.zeros_like(self.z[0])
        Zl = np.empty_like(self.z[0])
        Zv = np.empty_like(self.z[0])

        while any(ponteiro):
            i+=1
            self.Yinghui_method(ponteiro)
            lnphil, Zl[ponteiro] = self.lnphi_Z_based_on_deltaG(self.x[:,ponteiro], self.P[ponteiro], self.ph_L[ponteiro])
            lnphiv, Zv[ponteiro] = self.lnphi_Z_based_on_deltaG(self.y[:,ponteiro], self.P[ponteiro], self.ph_V[ponteiro])
            fl = np.exp(lnphil) * (self.x[:,ponteiro] * self.P[ponteiro][np.newaxis,:])
            fv = np.exp(lnphiv) * (self.y[:,ponteiro] * self.P[ponteiro][np.newaxis,:])
            razao[:,ponteiro] = np.divide(fl, fv, out = razao[:,ponteiro] / razao[:,ponteiro] * (1 + 1e-10),
                              where = fv != 0)
            #x1 = self.x[self.K==np.max(self.K,axis=0)]
            self.K[:,ponteiro] = razao[:,ponteiro] * self.K[:,ponteiro]
            stop_criteria = np.max(abs(razao[:,ponteiro] - 1), axis = 0)
            ponteiro_aux = ponteiro[ponteiro]
            ponteiro_aux[(stop_criteria < 1e-9) * (i>2)] = False
            ponteiro[ponteiro] = ponteiro_aux
            if i > 600:
                import pdb; pdb.set_trace()
                ponteiro[ponteiro] = False

        V = (self.z[:,ponteiro_save][self.x[:,ponteiro_save] != 0] - self.x[:,ponteiro_save][self.x[:,ponteiro_save] != 0]) / \
                          (self.y[:,ponteiro_save][self.x[:,ponteiro_save] != 0] - self.x[:,ponteiro_save][self.x[:,ponteiro_save] != 0])
        #V = (self.z[:,ponteiro_save] - self.x[:,ponteiro_save]) / \
        #    (self.y[:,ponteiro_save] - self.x[:,ponteiro_save])
        #den = (self.y[:,ponteiro_save] - self.x[:,ponteiro_save])
        #V[den==0] = 0

        #vols_V = np.sum(self.x[:,ponteiro_save] == 0, dtype=bool, axis = 0)
        vv = np.argwhere((self.x[:,ponteiro_save]!=0) == True)
        vols_V, ind = np.unique(vv[:,1],return_index = True)
        #V_aux = V[(self.x[:,ponteiro_save]!=0)]
        self.V[ponteiro_save] = V[ind]

        self.x[:,((self.V)<=0) + ((self.V)>=1)] = self.z[:,((self.V)<=0) + ((self.V)>=1)]
        self.y[:,((self.V)<=0) + ((self.V)>=1)] = self.z[:,((self.V)<=0) + ((self.V)>=1)]
        self.V[self.V<0] = 0
        self.V[self.V>1] = 1
        self.L = 1 - self.V

        self.L[ponteiro_save] = 1. - self.V[ponteiro_save]
        if any(np.sum(abs((self.V*self.y + self.L * self.x)-self.z),axis=0)>1e-4):
            import pdb; pdb.set_trace()
        ponteiro_1phase = np.zeros_like(self.V,dtype=bool)
        ponteiro_1phase[((self.V)<=0) + ((self.V)>=1)] = True
        ponteiro_1phase[~ponteiro_save] = True
        lnphil, Zl[ponteiro_1phase] = self.lnphi_Z_based_on_deltaG(self.x[:,ponteiro_1phase], self.P[ponteiro_1phase], self.ph_L[ponteiro_1phase])
        lnphiv, Zv[ponteiro_1phase] = self.lnphi_Z_based_on_deltaG(self.y[:,ponteiro_1phase], self.P[ponteiro_1phase], self.ph_V[ponteiro_1phase])
        ksi_L, ksi_V, rho_L, rho_V = self.update_EOS_dependent_properties(Zl, Zv)
        return ksi_L, ksi_V, rho_L, rho_V

    def solve_objective_function_Whitson_for_V(self, V, Vmax, Vmin, ponteiro):

        ponteiro_save = np.copy(ponteiro)
        i = 0
        while any(ponteiro):
            i+=1
            Vold = np.copy(V[ponteiro])
            f = np.sum((self.K[:,ponteiro] - 1) * self.z[:,ponteiro] / (1 + V[ponteiro][np.newaxis,:] *
                (self.K[:,ponteiro] - 1)), axis = 0)
            df = - np.sum((self.K[:,ponteiro] - 1) ** 2 * self.z[:,ponteiro] / (1 + V[ponteiro][np.newaxis,:] *
                (self.K[:,ponteiro] - 1)) ** 2, axis = 0)
            V[ponteiro] = V[ponteiro] - f / df #Newton-Raphson iterative method
            V_aux = V[ponteiro]
            V_aux[V_aux > Vmax[ponteiro]] = 0.5 * (Vmax[ponteiro] + Vold)[V_aux > Vmax[ponteiro]]
            V_aux[V_aux < Vmin[ponteiro]] = 0.5 * (Vmin[ponteiro] + Vold)[V_aux < Vmin[ponteiro]]
            V[ponteiro] = V_aux
            stop_criteria = abs(V[ponteiro] / Vold - 1)
            stop_criteria[Vold==0] = 0
            ponteiro_aux = ponteiro[ponteiro]
            ponteiro_aux[(stop_criteria < 1e-9)] = False
            ponteiro[ponteiro] = ponteiro_aux
            if any(np.isnan(V)): V[np.isnan(V)] = 0
            if i>100:
                print('Vloop')
                ponteiro[ponteiro] = False

        V[np.isinf(V)] = 1
        #V[np.isinf(V)] = 0

        self.x[:,ponteiro_save] = self.z[:,ponteiro_save] / (1 + self.V[ponteiro_save][np.newaxis,:] *
                                (self.K[:,ponteiro_save] - 1))
        ponteiro_inf = np.isinf(self.x).sum(axis=0,dtype=bool)
        ponteiro_nan = np.isnan(self.x).sum(axis=0,dtype=bool)
        self.x[:,ponteiro_inf+ponteiro_nan] = self.z[:,ponteiro_nan+ponteiro_inf]
        #self.x[np.isinf(self.x)] = self.z[np.isinf(self.x)]/
        self.y[:,ponteiro_save] = self.K[:,ponteiro_save] * self.x[:,ponteiro_save]
        self.y[self.y==0] = self.z[self.y==0]

    def molar_properties_Whitson(self, ponteiro):

        t0 = time.time()
        Lmax = np.max(self.K, axis = 0)/(np.max(self.K, axis = 0) - 1)
        Lmin = np.min(self.K, axis = 0)/(np.min(self.K, axis = 0) - 1)

        Vmax = 1. - Lmin
        Vmin = 1. - Lmax
        #Vmin = ((K1-KNc)*z[self.K==K1]-(1-KNc))/((1-KNc)*(K1-1))
        #proposed by Li et al for Whitson method

        Vmax[Vmax<Vmin] = abs(Vmax[Vmax<Vmin]) #add this tow lines to correct some problems with 1 component injection
        Vmax[abs(Vmax)<1] = 1 #add this tow lines to correct some problems with 1 component injection
        #Vmin[Vmin>Vmax] = -Vmax[Vmin>Vmax]
        self.V[ponteiro] = (Vmin[ponteiro] + Vmax[ponteiro]) * 0.5

        ponteiro_save = np.copy(ponteiro)
        razao = np.ones(self.z.shape)/2
        i = 0
        Zl = np.empty_like(self.V)
        Zv = np.empty_like(Zl)

        while any(ponteiro):
            i+=1
            Vold = np.copy(self.V)
            self.solve_objective_function_Whitson_for_V(self.V, Vmax, Vmin, np.copy(ponteiro))
            lnphil, Zl[ponteiro] = self.lnphi_Z_based_on_deltaG(self.x[:,ponteiro], self.P[ponteiro], self.ph_L[ponteiro])
            lnphiv, Zv[ponteiro] = self.lnphi_Z_based_on_deltaG(self.y[:,ponteiro], self.P[ponteiro], self.ph_V[ponteiro])
            fv = np.exp(lnphiv) * (self.y[:,ponteiro] * self.P[ponteiro][np.newaxis,:])
            fl = np.exp(lnphil) * (self.x[:,ponteiro] * self.P[ponteiro][np.newaxis,:])
            fv[(abs(fl)<1e-300) + (abs(fv)<1e-300)] = fl[(abs(fl)<1e-300) + (abs(fv)<1e-300)]
            fv[fv == 0] = 1e-30
            razao[:,ponteiro] = fl/fv
            if any(np.isnan(razao).flatten()):
                if razao.shape[1]<300:
                    import pdb; pdb.set_trace()
            razao[np.isnan(razao)] = 1
            razao[np.isinf(razao)] = 1
            self.K[:,ponteiro] = razao[:,ponteiro] * self.K[:,ponteiro]
            if any(np.isnan(self.K).flatten()): import pdb; pdb.set_trace()
            #stop_criteria = np.max((fv / fl - 1), axis = 0)
            stop_criteria = np.sum((razao[:,ponteiro] - 1)**2, axis = 0) #Dandekar's
            ponteiro_aux = ponteiro[ponteiro]
            ponteiro_aux[(stop_criteria < 1e-10)] = False
            ponteiro[ponteiro] = ponteiro_aux
            ponteiro[(abs(self.V)>1e200)] = False
            if i>100:
                print('Floop')
                #import pdb; pdb.set_trace()
                ponteiro[ponteiro] = False

        t1 = time.time()
        # THINK OF A BETTER WAY TO ORGANIZE THIS

        self.z[self.z==1e-30] = 0
        self.x[:,((self.V)<=0) + ((self.V)>=1)] = self.z[:,((self.V)<=0) + ((self.V)>=1)]
        self.y[:,((self.V)<=0) + ((self.V)>=1)] = self.z[:,((self.V)<=0) + ((self.V)>=1)]
        self.V[self.V<0] = 0
        self.V[self.V>1] = 1
        self.L = 1 - self.V
        ponteiro_1phase = np.zeros_like(self.V,dtype=bool)
        ponteiro_1phase[((self.V)<=0) + ((self.V)>=1)] = True
        ponteiro_1phase[~ponteiro_save] = True
        lnphil, Zl[ponteiro_1phase] = self.lnphi_Z_based_on_deltaG(self.x[:,ponteiro_1phase], self.P[ponteiro_1phase], self.ph_L[ponteiro_1phase])
        lnphiv, Zv[ponteiro_1phase] = self.lnphi_Z_based_on_deltaG(self.y[:,ponteiro_1phase], self.P[ponteiro_1phase], self.ph_V[ponteiro_1phase])

        ksi_L, ksi_V, rho_L, rho_V = self.update_EOS_dependent_properties(Zl, Zv)
        return ksi_L, ksi_V, rho_L, rho_V

    def get_dlnphidP(self, T, xij, P, ph):
        A, B = self.EOS.coefficients_cubic_EOS_vectorized(xij, P)
        Z = self.EOS.Z_vectorized(A, B, ph)
        dAdP = self.EOS.dA_dP()
        dBdP = self.EOS.dB_dP()
        dZdP = self.EOS.dZ_dP_parcial(dAdP, dBdP, Z, A, B)
        dlnphidP = self.EOS.dlnphi_dP(dAdP, dBdP, dZdP, Z, A, B)
        return dlnphidP

    def bubble_point_pressure(self, ponteiro):
        ponteiro_save = np.copy(ponteiro)
        self.x[:,ponteiro] = self.z[:,ponteiro] #self.x[:,ponteiro]
        y = np.copy(self.x)

        # Depende muito de Pbguess (chute inicial de Pb) - PROBLEMÃO AQUI
        #self.Pv[self.T > ctes.Tc] = self.Pv[self.T > ctes.Tc] * 0.62
        i = 0
        self.z[self.z<=1e-20] = 0
        Pb = ctes.Pb_guess*np.ones(len(self.P)) #np.sum(self.z * self.Pv[:,np.newaxis], axis = 0) * 0.62
        #Pb = np.sum(self.z[:,ponteiro] * self.Pv[:,np.newaxis], axis = 0)
        K = np.exp(5.37 * (1 + ctes.w) * (1 - 1 / (self.T / ctes.Tc)), dtype=np.double)[:,np.newaxis] / \
                (Pb / ctes.Pc[:,np.newaxis])
        while any(ponteiro):

            y[:,ponteiro] = self.x[:,ponteiro] * K[:,ponteiro]
            Pb_old = np.copy(Pb[ponteiro])

            lnphiv = self.lnphi_based_on_deltaG(y[:,ponteiro], Pb[ponteiro], self.ph_V[ponteiro])
            lnphil = self.lnphi_based_on_deltaG(self.x[:,ponteiro], Pb[ponteiro], self.ph_L[ponteiro])

            fil = np.exp(lnphil) * (self.x[:,ponteiro] * Pb[ponteiro][np.newaxis,:])

            phiv = np.exp(lnphiv)
            phil = np.exp(lnphil)

            dlnphildP = self.get_dlnphidP(self.T, self.x[:,ponteiro], Pb[ponteiro], self.ph_L[ponteiro])
            dlnphivdP = self.get_dlnphidP(self.T, y[:,ponteiro], Pb[ponteiro], self.ph_V[ponteiro])

            dlnfildP = self.EOS.dlnfij_dP(Pb[ponteiro], dlnphildP)
            dfildP = fil * dlnfildP
            dphivdP = phiv * dlnphivdP

            f = np.sum(fil/phiv, axis = 0) - Pb[ponteiro]
            df = np.sum((phiv * dfildP - fil * dphivdP) / phiv**2, axis=0) - 1.

            i += 1
            if i > 100 or any(Pb < 0):
                Pb[ponteiro] = 2 * self.P[ponteiro]
                ponteiro[ponteiro] = False
                break
                print("Not converged - assuming its gas")

            if any(df == 0):
                import pdb; pdb.set_trace()
                raise ValueError('Change Pguess - not converging')

            Pb[ponteiro] = Pb[ponteiro] - f / df
            K[:,ponteiro] = phil / phiv
            stop_criteria = abs(Pb[ponteiro] - Pb_old)
            ponteiro_aux = ponteiro[ponteiro]
            ponteiro_aux[stop_criteria <= .5*6894.757] = False
            ponteiro[ponteiro] = ponteiro_aux

        import pdb; pdb.set_trace()
        L = self.L[ponteiro_save]
        V = self.V[ponteiro_save]
        L[self.P[ponteiro_save] > Pb[ponteiro_save]] = 1
        V[self.P[ponteiro_save] > Pb[ponteiro_save]] = 0.
        L[self.P[ponteiro_save] < Pb[ponteiro_save]] = 0.
        V[self.P[ponteiro_save] < Pb[ponteiro_save]] = 1
        self.L[ponteiro_save] = L
        self.V[ponteiro_save] = V

    def update_EOS_dependent_properties(self, Zl, Zv):
        #self.EOS = ctes.EOS_class(self.P, self.T)
        ksi_L, rho_L = self.get_EOS_dependent_properties(self.T, self.x, self.P, Zl)
        ksi_V, rho_V = self.get_EOS_dependent_properties(self.T, self.y, self.P, Zv)
        return ksi_L, ksi_V, rho_L, rho_V

    def get_EOS_dependent_properties(self, T, xkj, P, Z):
        #l - any phase molar composition
        v = Z * ctes.R * T / P #vshift go here
        ksi_phase = 1 / v
        Mw_phase = np.sum(xkj * ctes.Mw[:,np.newaxis], axis = 0)
        rho_phase = ksi_phase * Mw_phase
        return ksi_phase, rho_phase

    '''def TPD(self, z): #ainda não sei onde usar isso
        x = np.zeros(self.Nc)

        #**********************Tangent Plane distance plot*********************#
        t = np.linspace(0.01, 0.99, 0.9 / 0.002) #vetor auxiliar
        TPD = np.zeros(len(t)) ##F

        for i in range(0, len(t)):
            aux = 0;
            lnphiz = self.lnphi(z, 1) #original phase

            #x = np.array([1-t[i],t[i]]) #new phase composition (1-t e t) - apenas válido para Nc=2 acredito eu.
            for k in range(0, ctes.Nc- 1):
                x[k] = (1 - t[i]) / (ctes.Nc- 1)
                x[ctes.Nc- 1] = t[i]

            ''''''O modo que x varia implica no formato de TPD. No presente exemplo,
            a fração molar do segundo componente de x varia direto com t, que é a
            variável de plotagem. Logo, a distancia dos planos tangentes será
            zero em z[Nc-1]. O contrário ocorreria''''''
            lnphix = self.lnphi(x, 0); #new phase (vapor- ph=2)
            for j in range(0,self.Nc):
                fix = math.exp(lnphix[j]) * x[j] * self.P
                fiz = math.exp(lnphiz[j]) * z[j] * self.P
                aux = aux + x[j] * ctes.R* self.T * (math.log(fix / fiz))
                TPD[i] = aux

        plt.figure(0)
        plt.plot(t, TPD)
        plt.xlabel('x')
        plt.ylabel('TPD')
        plt.show()
        return TPD'''
