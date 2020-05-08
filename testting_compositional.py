import pdb
from packs.running.compositional_initial_mesh_properties import initial_mesh
from packs.compositional.compositionalIMPEC import CompositionalFVM
from packs.directories import data_loaded
from run_compositional import run_simulation
import run_compositional
import scipy.sparse as sp
import numpy as np
from packs.compositional.update_time import delta_time
import matplotlib.pyplot as plt
import update_inputs_compositional

""" --------------------------For user to fill------------------------------ """

name_current = 'current_compositional_results_'
name_all = data_loaded['name_save_file'] + '_'
mesh = 'mesh/' + data_loaded['mesh_name']


delta_t_initial = data_loaded['compositional_data']['time_data']['delta_t_ini']
if data_loaded['use_vpi']:
    stop_criteria = max(data_loaded['compositional_data']['vpis_para_gravar_vtk'])
else: stop_criteria = max(data_loaded['compositional_data']['time_to_save'])

loop_max = 1000
run_criteria = 0

 #31536000 #1.3824*86400#365*86400#422693.9470089848 #seg #0.01* 86400

""" ----------------------------- RUN CODE --------------------------------- """

load = data_loaded['load_data']
convert = data_loaded['convert_english_to_SI']

M, data_impress, prop, wells, fprop, fprop_block, kprop, load, n_volumes = run_compositional.initialize(load, convert, mesh)

sim = run_simulation(delta_t_initial, data_impress, fprop, name_current, name_all)

while run_criteria < stop_criteria :# and loop < loop_max:

    sim.run(M, data_impress, wells, prop, fprop, fprop_block, kprop, load, n_volumes)

    if data_loaded['use_vpi']: run_criteria = sim.vpi
    else:
        run_criteria = sim.t
        if (sim.t + sim.delta_t) > stop_criteria:
            sim.delta_t = stop_criteria - sim.t
    print(run_criteria)
    #if (t + sim.delta_t) > sim.time_save:

print(fprop.P)
import pdb; pdb.set_trace()
sim.save_infos(data_impress, M)

'''
calculate the time of this test to compare results:
 t = 0.157 * porosity * viscosity * ct * L**2 / K #I figure ct stands for rock compressibility or total compressibility
 t = 0.157 * 0.2 * 2.498e(-4) * 7.25e-8 * 609.6**2/5e-13
'''
#data_impress.update_variables_to_mesh()
#M.core.print(file='test'+ str(n), extension='.vtk', config_input='input_cards/print_settings0.yml')
