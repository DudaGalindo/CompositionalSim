import numpy as np
from ..directories import data_loaded
from ..utils import constants as ctes
from .stability_check import StabilityCheck
from .properties_calculation import PropertiesCalc
import scipy.sparse as sp
from scipy import linalg
from scipy import interpolate
import scipy.linalg as la

class FOUM:

    def update_flux(self, fprop, total_flux_internal_faces, phase_densities_internal_faces, mobilities_internal_faces):
        self.update_phase_flux_internal_faces(fprop, total_flux_internal_faces, phase_densities_internal_faces, mobilities_internal_faces)
        component_flux_internal_faces = self.update_component_flux_internal_faces(
        fprop.component_molar_fractions_internal_faces,fprop.phase_molar_densities_internal_faces)
        self.update_flux_volumes(fprop, component_flux_internal_faces)

    def update_phase_flux_internal_faces(self, fprop, total_flux_internal_faces, phase_densities_internal_faces, mobilities_internal_faces):
        z = ctes.z[ctes.v0[:,0]]
        z_up = ctes.z[ctes.v0[:,1]]

        frj = mobilities_internal_faces[0,...] / np.sum(mobilities_internal_faces[0,...], axis = 0)

        self.phase_flux_internal_faces = frj[np.newaxis,...] * (total_flux_internal_faces +
                                        ctes.pretransmissibility_internal_faces * (np.sum(mobilities_internal_faces *
                                        (fprop.Pcap[:,ctes.v0[:,1]] - fprop.Pcap[:,ctes.v0[:,0]] - ctes.g *
                                        phase_densities_internal_faces * (z_up - z)), axis=1) - \
                                        np.sum(mobilities_internal_faces, axis=1) * (fprop.Pcap[:,ctes.v0[:,1]] -
                                        fprop.Pcap[:,ctes.v0[:,0]] - ctes.g *phase_densities_internal_faces * (z_up - z))))
        # M.flux_faces[M.faces.internal] = total_flux_internal_faces * M.faces.normal[M.faces.internal].T

    def update_component_flux_internal_faces(self, component_molar_fractions_internal_faces, phase_molar_densities_internal_faces):
        component_flux_internal_faces = np.sum(component_molar_fractions_internal_faces * phase_molar_densities_internal_faces *
                                self.phase_flux_internal_faces, axis = 1)
        return component_flux_internal_faces

    def update_flux_volumes(self, fprop, component_flux_internal_faces):
        cx = np.arange(ctes.n_components)
        lines = np.array([np.repeat(cx,len(ctes.v0[:,0])), np.repeat(cx,len(ctes.v0[:,1]))]).astype(int).flatten()
        cols = np.array([np.tile(ctes.v0[:,0],ctes.n_components), np.tile(ctes.v0[:,1], ctes.n_components)]).flatten()
        data = np.array([-component_flux_internal_faces, component_flux_internal_faces]).flatten()
        fprop.component_flux_vols_total = sp.csc_matrix((data, (lines, cols)), shape = (ctes.n_components, ctes.n_volumes)).toarray()


class MUSCL:

    """Class created for the second order MUSCL implementation for the calculation of the advective terms"""

    def run(self, M, fprop, wells, P_old, ftot):
        self.total_flux_internal_faces = ftot
        #self.fk_vols = fprop.component_flux_vols_total
        dNk_vols = self.volume_gradient_reconstruction(M, fprop, wells)
        dNk_face, dNk_face_neig = self.get_faces_gradient(M, fprop, dNk_vols)
        phi = self.Van_Leer_slope_limiter(dNk_face, dNk_face_neig); self.phi = phi

        Nk_face, z_face = self.get_extrapolated_compositions(fprop, phi, dNk_face_neig)
        self.mobilities_face, self.phase_densities_face, self.phase_molar_densities_face, \
        self.component_molar_fractions_face = self.get_extrapolated_properties(fprop,
                                                        M, Nk_face, z_face, P_old)
        G = self.update_gravity_term()
        alpha = self.update_flux(M, fprop, G, Nk_face, P_old)
        return alpha

    def volume_gradient_reconstruction(self, M, fprop, wells):
        neig_vols = M.volumes.bridge_adjacencies(M.volumes.all,2,3)
        matriz = np.zeros((ctes.n_volumes,ctes.n_volumes))

        lines = np.array([ctes.v0[:, 0], ctes.v0[:, 1], ctes.v0[:, 0], ctes.v0[:, 1]]).flatten()
        cols = np.array([ctes.v0[:, 1], ctes.v0[:, 0], ctes.v0[:, 0], ctes.v0[:, 1]]).flatten()
        data = np.array([np.ones(len(ctes.v0[:, 0])), np.ones(len(ctes.v0[:, 0])),
                        np.zeros(len(ctes.v0[:, 0])), np.zeros(len(ctes.v0[:, 0]))]).flatten()
        all_neig = sp.csc_matrix((data, (lines, cols)), shape = (ctes.n_volumes, ctes.n_volumes)).toarray()
        all_neig = all_neig.astype(int)
        all_neig2 = all_neig + np.identity(ctes.n_volumes)
        allneig2 = all_neig2.astype(int)

        Nk_neig =  fprop.component_mole_numbers[:,np.newaxis,:] * all_neig2[np.newaxis,:,:]
        Nk = Nk_neig.transpose(0,2,1)
        pos_neig = M.data['centroid_volumes'].T[:,np.newaxis,:] * all_neig2[np.newaxis,:,:]
        pos = pos_neig.transpose(0,2,1)

        ds = pos_neig - pos
        ds_norm = np.linalg.norm(ds, axis=0)
        versor_ds = np.empty(ds.shape)
        versor_ds[:,ds_norm==0] = 0
        versor_ds[:,ds_norm!=0] = ds[:,ds_norm!=0] / ds_norm[ds_norm!=0]
        dNk = Nk_neig - Nk

        dNk_by_axes = np.repeat(dNk[:,np.newaxis,:,:],3,axis=1)
        dNk_by_axes = dNk_by_axes * versor_ds
        dNk_vols = dNk_by_axes.sum(axis = 3)

        ds_vols = ds * versor_ds
        ds_vols = ds_vols.sum(axis = 2)
        dNkds_vols = np.copy(dNk_vols)
        dNkds_vols[:,ds_vols!=0] = dNk_vols[:,ds_vols != 0] / ds_vols[ds_vols != 0][np.newaxis,:]
        self.all_neig = all_neig.sum(axis=1)
        self.identify_contour_faces()
        dNkds_vols[:,:,all_neig.sum(axis=1)==1] = 0 #*dNkds_vols[:,:,all_neig.sum(axis=1)==1]
        #dNkds_vols[:,:,ctes.v0[self.faces_contour].flatten()] = 0
        return dNkds_vols

    def get_faces_gradient(self, M, fprop, dNkds_vols):
        dNk_face =  fprop.component_mole_numbers[:,ctes.v0[:,1]] - fprop.component_mole_numbers[:,ctes.v0[:,0]]
        ds_face = M.data['centroid_volumes'][ctes.v0[:,1],:] -  M.data['centroid_volumes'][ctes.v0[:,0],:]
        dNk_face_vols = 2. * (dNkds_vols[:,:,ctes.v0] * ds_face.T[np.newaxis,:,:,np.newaxis]).sum(axis=1)
        dNk_face_neig = dNk_face_vols - dNk_face[:,:,np.newaxis]
        return dNk_face, dNk_face_neig

    def Van_Leer_slope_limiter(self, dNk_face, dNk_face_neig):
        np.seterr(divide='ignore', invalid='ignore')
        r_face = dNk_face[:,:,np.newaxis] / dNk_face_neig
        r_face[dNk_face_neig==0] = 0
        phi = (r_face + abs(r_face)) / (r_face + 1)
        phi[r_face<0]=0 #so botei pra caso r==-1
        phi[:,:,1] = -phi[:,:,1]
        return phi

    def get_extrapolated_compositions(self, fprop, phi, dNk_face_neig):
        Nk_face = fprop.component_mole_numbers[:,ctes.v0] + phi / 2 * dNk_face_neig
        z_face = Nk_face[0:ctes.Nc] / np.sum(Nk_face[0:ctes.Nc], axis = 0)
        return Nk_face, z_face

    def get_extrapolated_properties(self, fprop, M, Nk_face, z_face, P_old, v=2):
        L_face = np.empty((len(M.faces.internal), v))
        V_face = np.empty((len(M.faces.internal), v))
        Sw_face = np.empty((len(M.faces.internal), v))
        So_face = np.empty((len(M.faces.internal), v))
        Sg_face = np.empty((len(M.faces.internal), v))
        ksi_W_face = np.empty_like(Sw_face)
        rho_W_face = np.empty_like(Sw_face)
        component_molar_fractions_face = np.empty((ctes.n_components, ctes.n_phases, len(M.faces.internal), v))
        phase_molar_densities_face = np.empty((1, ctes.n_phases, len(M.faces.internal), v))
        phase_densities_face = np.empty((1, ctes.n_phases, len(M.faces.internal), v))
        mobilities_face = np.empty((1, ctes.n_phases, len(M.faces.internal), v))
        #Vp = PropertiesCalc().update_porous_volume(P_old)

        self.P_face = np.sum(P_old[ctes.v0], axis=1) * 0.5
        #self.P_face[self.faces_contour] = np.max(P_old[ctes.v0][self.faces_contour],axis=1) #upwind nas faces do contorno
        #self.P_face = np.max(P_old[ctes.v0],axis=1)
        for i in range(0,v):
            #self.P_face = P_old[ctes.v0[:,i]]
            #self.P_face[self.faces_contour] = np.sum(P_old[ctes.v0][self.faces_contour],axis=1) * 0.5
            if ctes.compressible_k:
                L_face[:,i], V_face[:,i], component_molar_fractions_face[0:ctes.Nc,0,:,i], \
                component_molar_fractions_face[0:ctes.Nc,1,:,i], phase_molar_densities_face[:,0,:,i], \
                phase_molar_densities_face[:,1,:,i], phase_densities_face[:,0,:,i], \
                phase_densities_face[:,1,:,i]  =  StabilityCheck(fprop, self.P_face).run(fprop, self.P_face, \
                                                                L_face[:,i], V_face[:,i], z_face[:,:,i])
            else:
                L_face[:,i] = 1; V_face[:,i] = 0; component_molar_fractions_face[0:ctes.Nc,0:2,:,i] = 1
                phase_densities_face[:,:,:,i] = fprop.phase_densities[:,:,ctes.v0[:,i]]
                phase_molar_densities_face[:,:,:,i] = fprop.phase_molar_densities[:,:,ctes.v0[:,i]]

            if ctes.load_w:
                component_molar_fractions_face[-1,-1,:,i] = 1
                component_molar_fractions_face[-1,0:-1,:,i] = 0
                component_molar_fractions_face[0:ctes.Nc,-1,:,i] = 0

                Sw_face[:,i], phase_molar_densities_face[0,-1,:,i], phase_densities_face[0,-1,:,i] = \
                PropertiesCalc().update_water_saturation(fprop, Nk_face[-1,:,i], self.P_face, \
                                                        fprop.Vp[ctes.v0[:,i]])

            So_face[:,i], Sg_face[:,i] =  PropertiesCalc().update_saturations(Sw_face[:,i],
                                phase_molar_densities_face[:,:,:,i], L_face[:,i], V_face[:,i])
            mobilities_face[:,:,:,i] = PropertiesCalc().update_mobilities(fprop, So_face[:,i], Sg_face[:,i],
                                        Sw_face[:,i], phase_molar_densities_face[:,:,:,i],
                                        component_molar_fractions_face[:,:,:,i])

        return mobilities_face, phase_densities_face, phase_molar_densities_face, component_molar_fractions_face

    def update_gravity_term(self):
        G = ctes.g * self.phase_densities_face * ctes.z[ctes.v0]
        return G

    def flux_calculation_conditions(self, dFkdNk):
        ponteiro_LLF = np.zeros(ctes.n_internal_faces,dtype=bool)
        '''ponteiro_LLF = np.ones((ctes.n_components,ctes.n_internal_faces),dtype=bool)
        ponteiro_aux = np.copy(~ponteiro_LLF)
        ponteiro_LLF[dFkdNk[:,:,0] * dFkdNk[:,:,1] <= 0] = False
        cond = np.empty((ctes.n_components,ctes.n_internal_faces))
        for k in range(ctes.n_components-1):
            cond[k] = np.min(abs(dFkdNk[k,:,0] - dFkdNk[k+1:,:,0]),axis=0)
        cond[-1] = np.min(abs(dFkdNk[-1,:,0] - dFkdNk[0:-1,:,0]),axis=0)
            #cond[k,:,1] = np.min(abs(dFkdNk[k,:,1] - dFkdNk[k+1:,:,1]),axis=0)
        ponteiro_aux[dFkdNk[:,:,0]==dFkdNk[:,:,1]] = True
        ponteiro_LLF2 = ponteiro_LLF[ponteiro_aux]
        ponteiro_LLF2[cond[ponteiro_aux]<0.01*np.max(abs(dFkdNk[ponteiro_aux,0]),axis=0)] = False
        ponteiro_LLF[ponteiro_aux] = ponteiro_LLF2
        ponteiro_LLF = ponteiro_LLF.sum(axis=0,dtype=bool)'''
        return ponteiro_LLF

    def identify_contour_faces(self):
        vols_contour = np.argwhere(self.all_neig==1).flatten()
        self.faces_contour = np.empty_like(vols_contour)

        for i in range(len(vols_contour)):
            try: self.faces_contour[i] = np.argwhere(ctes.v0[:,0] == vols_contour[i]).flatten()
            except: self.faces_contour[i] = np.argwhere(ctes.v0[:,1] == vols_contour[i]).flatten()

    def update_flux(self, M, fprop, G, Nk_face, P_old):
        component_flux_internal_faces = np.empty((ctes.n_components,ctes.n_internal_faces))
        #alphaLR = self.get_LR_eigenvalues(M, fprop, Nk_face, P_old)
        LLF = data_loaded['compositional_data']['MUSCL']['LLF']
        DW = data_loaded['compositional_data']['MUSCL']['DW']
        if LLF:
            ponteiro = np.zeros(ctes.n_internal_faces,dtype=bool)
            #ponteiro = self.flux_calculation_conditions(alphaLR)
            Fk_face, alpha = self.wave_velocity_LLF(M, fprop, Nk_face, P_old)
            component_flux_internal_faces[:,~ponteiro], alpha_wv = self.update_flux_LLF(Fk_face[:,~ponteiro,:],
                                                    Nk_face[:,~ponteiro,:], alpha[:,~ponteiro,:])
        if DW:
            Fk_face, alpha = self.wave_velocity_DW(M, fprop, Nk_face, P_old)
            component_flux_internal_faces[:,~ponteiro], alpha_wv = self.update_flux_DW(Fk_face[:,~ponteiro,:],
                                                    Nk_face[:,~ponteiro,:], alpha[:,~ponteiro])
        if any(ponteiro):
            Fk_face = self.get_component_flux_face(fprop)
            alpha_wv = 0
            import pdb; pdb.set_trace()
            component_flux_internal_faces[:,ponteiro] = self.update_flux_upwind(fprop, G,
                                                Fk_face[:,ponteiro,:], np.copy(ponteiro))

        FOUM().update_flux_volumes(fprop, component_flux_internal_faces)
        #import pdb; pdb.set_trace()
        #if fprop.Sw[0]>0.4:import pdb; pdb.set_trace()
        return alpha_wv

    def Fk_Nk(self, fprop, M, Nk, P_old):
        z = Nk[0:ctes.Nc] / np.sum(Nk[0:ctes.Nc], axis = 0)
        Nk = Nk[:,:,np.newaxis]
        z = z[:,:,np.newaxis]
        mobilities, phase_densities, phase_molar_densities, \
        component_molar_fractions = self.get_extrapolated_properties(fprop,
                                                        M, Nk, z, P_old,v=1)
        ftotal = self.total_flux_internal_faces
        f = FOUM()
        f.update_phase_flux_internal_faces(fprop, ftotal,
                    phase_densities[:,:,:,0], mobilities[:,:,:,0])
        Fk = f.update_component_flux_internal_faces(component_molar_fractions[:,:,:,0],
                         phase_molar_densities[:,:,:,0])
        return Fk

    def get_component_flux_face(self, fprop):
        Fk_face = np.empty((ctes.n_components,ctes.n_internal_faces, 2))
        for i in range(2):
            f = FOUM()
            f.update_phase_flux_internal_faces(fprop, self.total_flux_internal_faces,
                        self.phase_densities_face[:,:,:,i], self.mobilities_face[:,:,:,i])
            Fk_face[:,:,i] = f.update_component_flux_internal_faces(self.component_molar_fractions_face[:,:,:,i],
                             self.phase_molar_densities_face[:,:,:,i])

        return Fk_face

    def get_LR_eigenvalues(self, M, fprop, Nk_face, P_old):
        dFkdNk = np.empty((ctes.n_internal_faces, ctes.n_components, ctes.n_components))
        dFkdNk_eigvalue = np.empty((ctes.n_components,ctes.n_internal_faces, 2))
        delta = 0.0001
        for i in range(2):
            for k in range(ctes.n_components):
                Nk_face_plus = np.copy(Nk_face[:,:,i])
                Nk_face_minus = np.copy(Nk_face_plus)
                Nk_face_plus[k] += delta/2
                Nk_face_minus[k] -= delta/2
                dFkdNk[:,:,k] = (self.Fk_Nk(fprop, M, Nk_face_plus, P_old) -
                                    self.Fk_Nk(fprop, M, Nk_face_minus, P_old)).T/delta

            eigval1, v = np.linalg.eig(dFkdNk)
            dFkdNk_eigvalue[:,:,i] = eigval1.T

        return dFkdNk_eigvalue


    def wave_velocity_LLF(self, M, fprop, Nk_face, P_old):
        np.seterr(divide='ignore', invalid='ignore')
        delta = 0.0001
        dFkdNk = np.empty((ctes.n_internal_faces, ctes.n_components, ctes.n_components))
        dFkdNk_eigvalue = np.empty((ctes.n_components,ctes.n_internal_faces, 2))
        Fk_face = np.empty((ctes.n_components,ctes.n_internal_faces, 2))
        dFkdNk_gauss = np.empty((ctes.n_internal_faces, ctes.n_components, ctes.n_components))
        dFkdNk_m = np.empty((ctes.n_internal_faces, ctes.n_components, ctes.n_components))
        dFkdNk_gauss_eigvalue = np.empty_like(Fk_face)
        dFkdNk_m_eigvalue = np.empty_like(Fk_face[:,:,0])

        Nkm = (Nk_face[:,:,1] + Nk_face[:,:,0])/2

        for i in range(2):
            f = FOUM()
            f.update_phase_flux_internal_faces(fprop, self.total_flux_internal_faces,
                        self.phase_densities_face[:,:,:,i], self.mobilities_face[:,:,:,i])
            Fk_face[:,:,i] = f.update_component_flux_internal_faces(self.component_molar_fractions_face[:,:,:,i],
                             self.phase_molar_densities_face[:,:,:,i])

            Nkg = Nkm + (Nk_face[:,:,i] - Nkm)/(3**(1/2))

            for k in range(0,ctes.n_components):
                Nk_face_plus = np.copy(Nk_face[:,:,i])
                Nk_face_minus = np.copy(Nk_face[:,:,i])
                Nk_face_plus[k] += delta*0.5
                Nk_face_minus[k] -= delta*0.5
                Nk_face_plus[Nk_face_plus>np.max(Nk_face,axis=2)] = Nk_face[Nk_face_plus>np.max(Nk_face,axis=2),i]
                Nk_face_minus[Nk_face_minus<np.min(Nk_face,axis=2)] = Nk_face[Nk_face_minus<np.min(Nk_face,axis=2),i]
                dFkdNk[:,:,k] = ((self.Fk_Nk(fprop, M, Nk_face_plus, P_old) -
                                self.Fk_Nk(fprop, M, Nk_face_minus, P_old))/
                                (Nk_face_plus[k]-Nk_face_minus[k])).T

                Nkg_plus = np.copy(Nkg)
                Nkg_minus = np.copy(Nkg)
                Nkg_plus[k] += delta*0.5
                Nkg_minus[k] -= delta*0.5
                Nkg_plus[Nkg_plus>np.max(Nk_face,axis=2)] = Nkg[Nkg_plus>np.max(Nk_face,axis=2)]
                Nkg_minus[Nkg_minus<np.min(Nk_face,axis=2)] = Nkg[Nkg_minus<np.min(Nk_face,axis=2)]
                dFkdNk_gauss[:,:,k] = ((self.Fk_Nk(fprop, M, Nkg_plus, P_old) -
                                    self.Fk_Nk(fprop, M, Nkg_minus, P_old))/
                                    (Nkg_plus[k]-Nkg_minus[k])).T
                if i==0:
                    Nkm_plus = np.copy(Nkm)
                    Nkm_minus = np.copy(Nkm)
                    Nkm_plus[k] += delta*0.5
                    Nkm_minus[k] -= delta*0.5
                    Nkm_plus[Nkm_plus>np.max(Nk_face,axis=2)] = Nkm[Nkm_plus>np.max(Nk_face,axis=2)]
                    Nkm_minus[Nkm_minus<np.min(Nk_face,axis=2)] = Nkm[Nkm_minus<np.min(Nk_face,axis=2)]
                    dFkdNk_m[:,:,k] = ((self.Fk_Nk(fprop, M, Nkm_plus, P_old) -
                            self.Fk_Nk(fprop, M, Nkm_minus, P_old))/
                            (Nkm_plus[k]-Nkm_minus[k])).T

                dFkdNk[(Nk_face_plus-Nk_face_minus).T==0,k] = 0
                dFkdNk_m[(Nkm_plus-Nkm_minus).T==0,k] = 0
                dFkdNk_gauss[(Nkg_plus-Nkg_minus).T==0,k] = 0


            eigval1, v = np.linalg.eig(dFkdNk)
            dFkdNk_eigvalue[:,:,i] = eigval1.T
            eigval2, v = np.linalg.eig(dFkdNk_gauss)
            dFkdNk_gauss_eigvalue[:,:,i] = eigval2.T

        eigval3, v = np.linalg.eig(dFkdNk_m)
        dFkdNk_m_eigvalue = eigval3.T
        alpha = np.concatenate((dFkdNk_eigvalue, dFkdNk_gauss_eigvalue), axis=-1)
        alpha = np.concatenate((alpha, dFkdNk_m_eigvalue[:,:,np.newaxis]), axis=-1)
        #alpha = (Fk_face[:,:,1] - Fk_face[:,:,0]) / (Nk_face[:,:,1] - Nk_face[:,:,0])
        #alpha[(Nk_face[:,:,1] - Nk_face[:,:,0])<=0.01] = dFkdNk_m[(Nk_face[:,:,1] - Nk_face[:,:,0])<=0.01]
        #alpha[(Fk_face[:,:,1] - Fk_face[:,:,0])==0] = 0
        return Fk_face, alpha

    def wave_velocity_DW(self, M, fprop, Nk_face, P_old):
        np.seterr(divide='ignore', invalid='ignore')
        delta = 0.0001
        Nkm = (Nk_face[:,:,1] + Nk_face[:,:,0])/2
        Fk_face = np.empty((ctes.n_components,ctes.n_internal_faces, 2))

        dFkdNk_RLG = np.empty_like(Fk_face)
        dFkdNk_MG = np.empty_like(Fk_face)
        dFkdNk_m = np.empty((ctes.n_internal_faces, ctes.n_components, ctes.n_components))

        for i in range(2):
            f = FOUM()
            f.update_phase_flux_internal_faces(fprop, self.total_flux_internal_faces,
                        self.phase_densities_face[:,:,:,i], self.mobilities_face[:,:,:,i])
            Fk_face[:,:,i] = f.update_component_flux_internal_faces(self.component_molar_fractions_face[:,:,:,i],
                             self.phase_molar_densities_face[:,:,:,i])
            if i==0:
                for k in range(ctes.n_components):

                    Nkm_plus = np.copy(Nkm)
                    Nkm_minus = np.copy(Nkm)
                    Nkm_plus[k,:] += delta/2
                    Nkm_minus[k,:] -= delta/2
                    dFkdNk_m[:,:,k] = (self.Fk_Nk(fprop, M, Nkm_plus, P_old) -
                                self.Fk_Nk(fprop, M, Nkm_minus, P_old)).T/delta
            '''Nkg = Nkm + (Nk_face[:,:,i] - Nkm)/3**(1/2)
            dFkdNk_RLG[:,:,i] = (self.Fk_Nk(fprop, M, Nk_face[:,:,i], P_old) -
                                self.Fk_Nk(fprop, M, Nkg, P_old))/(Nk_face[:,:,i] - Nkg)

            dFkdNk_MG[:,:,i] = (self.Fk_Nk(fprop, M, Nkm, P_old) -
                                self.Fk_Nk(fprop, M, Nkg, P_old))/(Nkm - Nkg)
            dFkdNk_RLG[(Nk_face[:,:,i] - Nkg)==0] = 0;
            dFkdNk_MG[(Nkm - Nkg)==0] = 0''' #THIS WAS FOR MDW SCHEME

        eigval, v = np.linalg.eig(dFkdNk_m)
        dFkdNk_m = eigval.T
        alpha = (Fk_face[:,:,1] - Fk_face[:,:,0]) / (Nk_face[:,:,1] - Nk_face[:,:,0])
        alpha[(Nk_face[:,:,1] - Nk_face[:,:,0])<=0.01] = dFkdNk_m[(Nk_face[:,:,1] - Nk_face[:,:,0])<=0.01]
        return Fk_face, alpha

    def update_flux_upwind(self, fprop, G, Fk_face_upwind_all, ponteiro_LLF):
        Fk_face_upwind = np.empty_like(Fk_face_upwind_all[:,:,0])
        Pot_hid = fprop.P #+ fprop.Pcap
        Pot_hidj = Pot_hid[ctes.v0[:,0]][ponteiro_LLF] #- G[0,:,:,0]
        Pot_hidj_up = Pot_hid[ctes.v0[:,1]][ponteiro_LLF] #- G[0,:,:,1]
        #dFkdNk_face_upwind = np.sum(dFkdNk_face_upwind_all,axis=-1)

        #alpha[(Fk_face[:,:,1] - Fk_face[:,:,0])==0] = 0
        #Fk_face_upwind = 0.5*(Fk_face_upwind_all.sum(axis=-1) - np.max(abs(dFkdNk_m_upwind),axis=0) *
        #                (Nk_face_upwind[:,:,1] - Nk_face_upwind[:,:,0]))

        Fk_face_upwind[:,Pot_hidj_up <= Pot_hidj] = Fk_face_upwind_all[:,Pot_hidj_up <= Pot_hidj, 0]
        Fk_face_upwind[:,Pot_hidj_up > Pot_hidj] = Fk_face_upwind_all[:,Pot_hidj_up > Pot_hidj, 1]
        #if any(alpha_upwind < 0): import pdb; pdb.set_trace()
        return Fk_face_upwind

    def update_flux_DW(self, Fk_face_DW_all, Nk_face_DW, alpha_DW):
        Fk_face_DW = 0.5*(Fk_face_DW_all.sum(axis=-1) - abs(alpha_DW) * \
                    (Nk_face_DW[:,:,1] - Nk_face_DW[:,:,0]))
        alpha = np.max(abs(alpha_DW),axis = 0)
        return Fk_face_DW, alpha

    def update_flux_LLF(self, Fk_face_LLF_all, Nk_face_LLF, alpha_LLF):
        alpha = np.max(abs(alpha_LLF),axis = 0)
        Fk_face_LLF = 0.5*(Fk_face_LLF_all.sum(axis=-1) - np.max(abs(alpha),axis=-1) * \
                    (Nk_face_LLF[:,:,1] - Nk_face_LLF[:,:,0]))
        return Fk_face_LLF, alpha
