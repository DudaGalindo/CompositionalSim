import numpy as np
from ..utils import constants as ctes
from ..directories import data_loaded

class delta_time:
    def __init__(self, fprop):
        self.P = fprop.P
        self.So = fprop.So
        self.Sg = fprop.Sg
        self.Sw = fprop.Sw
        self.Nk = fprop.Nk
        'the initialization of this class is made in a different time step \
        evaluation'

    def update_CFL(delta_t, fprop, wells, Fk_vols_total, Nks, wave_velocity):
        CFL_p = data_loaded['compositional_data']['CFL']
        old_settings = np.seterr(all = 'ignore', divide = 'ignore')
        CFLs = np.zeros([3])
        CFLs[0] = delta_t * np.max(abs(wave_velocity))
        Nk = np.copy(Nks)
        #if CFL>100:
            #print(np.max(abs(wave_velocity)))
        Nk[Nk==0] = 1e300
        CFLs[1:] = delta_t*np.max(abs(fprop.qk_molar[:,wells['all_wells']]/Nk[:,wells['all_wells']]))
        CFL = max(CFLs)

        CFL = CFL*(2*(ctes.n_points-1)+1)

        #CFL_wells = delta_t * 1 / np.nanmin((Nk[wells['ws_inj']] /
        #           abs(Fk_vols_total[wells['ws_inj']])))
        #import pdb; pdb.set_trace()
        if (CFL - CFL_p)>1e-10:
            delta_t = delta_t / 2
        #delta_tmin = data_loaded['compositional_data']['time_data']['delta_tmin']
        #if delta_t<delta_tmin: delta_t=delta_tmin
        #delta_tcfl = np.nanmin(CFL * (fprop.Nk) / fprop.component_flux_vols_total, axis = 1) #make nan
        np.seterr(**old_settings)
        return delta_t

    def update_delta_tcfl(self, delta_t, fprop, wells):
         CFL = data_loaded['compositional_data']['CFL']
         old_settings = np.seterr(all = 'ignore', divide = 'ignore')
         delta_tcfl = np.zeros([3])-10000
         Nk = np.copy(self.Nk)

         delta_tcfl[0] = CFL / np.max(abs(fprop.wave_velocity)) #make nan
         Nk[Nk==0] = 1e-100
         #import pdb; pdb.set_trace()
         delta_tcfl[1:] = CFL/np.max(abs(fprop.qk_molar[:,wells['all_wells']]/Nk[:,wells['all_wells']]))#,axis=0)
         delta_tcfl = min(abs(delta_tcfl))

         np.seterr(**old_settings)

         delta_tcfl = delta_tcfl/(2*(ctes.n_points-1)+1)
         return delta_tcfl

    def update_delta_tp(self, delta_t, fprop, deltaPlim):
        deltaPmax = max(np.abs(fprop.P - self.P) / fprop.P)
        delta_tp = delta_t * deltaPlim / deltaPmax
        return delta_tp

    def update_delta_ts(self, delta_t, fprop, deltaSlim):
        old_settings = np.seterr(all = 'ignore', divide = 'ignore')
        deltaSo = np.abs(fprop.So - self.So) #/ fprop.So
        deltaSg = np.abs(fprop.Sg - self.Sg) #/ fprop.Sg
        deltaSw = np.abs(fprop.Sw - self.Sw) #/ fprop.Sw

        deltasS = np.array([deltaSo,deltaSg,deltaSw])
        deltaSmax = np.nanmax(deltasS)
        np.seterr(**old_settings)

        delta_ts = delta_t * deltaSlim / deltaSmax
        return delta_ts

    def update_delta_tn(self, delta_t, fprop, deltaNlim):
        old_settings = np.seterr(all = 'ignore', divide = 'ignore')
        dN = np.abs(fprop.Nk - self.Nk) / fprop.Nk
        dN[fprop.Nk<1e-30] = 0
        deltaNmax = max(np.nanmax(dN, axis =1))
        delta_tn = delta_t * deltaNlim / deltaNmax
        np.seterr(**old_settings)
        return delta_tn

    def update_delta_tv(self, delta_t, fprop, deltaVlim):
        old_settings = np.seterr(all = 'ignore', divide = 'ignore')
        deltaVmax = np.max(np.abs(fprop.Vt - fprop.Vp) / fprop.Vp)
        #deltaVlim = np.max(5e-4/fprop.Vp)
        delta_tv = delta_t * deltaVlim / deltaVmax
        np.seterr(**old_settings)
        return delta_tv

    def update_delta_t(self, delta_t, fprop, wells, load_k, loop):

        deltaPlim = data_loaded['compositional_data']['time_data']['deltaPlim']
        deltaSlim = data_loaded['compositional_data']['time_data']['deltaSlim']
        deltaNlim = data_loaded['compositional_data']['time_data']['deltaNlim']
        deltaVlim = data_loaded['compositional_data']['time_data']['deltaVlim']
        delta_tmax = data_loaded['compositional_data']['time_data']['delta_tmax']
        delta_tmin = data_loaded['compositional_data']['time_data']['delta_tmin']

        delta_tp = self.update_delta_tp(delta_t, fprop, deltaPlim)
        delta_ts = self.update_delta_ts(delta_t, fprop, deltaSlim)
        delta_tn = self.update_delta_tn(delta_t, fprop, deltaNlim)
        delta_tv = self.update_delta_tv(delta_t, fprop, deltaVlim)
        delta_tcfl = self.update_delta_tcfl(delta_t, fprop, wells)

        'If only water present, the time-step calculation follows the CFL criteria\
        Else, it follows the compositional regular criteria'
        if ctes.Cw == 0 and not load_k: delta_t = delta_tcfl
        else: delta_t = min(delta_tp, delta_ts, delta_tn, delta_tv)

        #delta_t = delta_tcfl

        if delta_t > min(delta_tmax,delta_tcfl): delta_t = min(delta_tmax, delta_tcfl)
        #if delta_t > delta_tmax: delta_t = delta_tmax

        if delta_t == delta_ts: print('S')
        if delta_t == delta_tcfl: print('CFL')
        if delta_t == delta_tv: print('V')
        if delta_t == delta_tn: print('N')
        if delta_t < delta_tmin: delta_t = delta_tmin
        return delta_t
