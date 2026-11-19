import os
path = '/home/pcuser/.2pac_logs'
os.chdir(path)

import qcodes as qc

import matplotlib.pyplot as plt
import seaborn as sns
sns.set_theme()

# Point to database

def main(run_id, export_data = False):
    qc.config['core']['db_location'] = '2pac.db'

    # Load a DataSet by its run ID
    # interesting run IDs: (160, 148 (quench), 152 (ramped up, slow close), 177 (He3, no magnet), 180 (He3, magnet), 164 (just cool off with open charcoal))


    if export_data:
        dataset = qc.load_by_id(run_id)
        dataset.export("csv", path = '/home/pcuser/run_data/')
    
    plot_data(run_id)


def plot_data(run_id):
    if run_id <= 154:
        press_unit = 'Pressure (abs. torr)'
    else:
        press_unit = 'Pressure (abs. bar)'
    params = ['cryocon_chA_temperature', 'cryocon_chB_temperature', 'cryocon_chC_temperature', 'cryocon_chD_temperature', 
            'labjack_kepco_current', 'ls370_heater_out', 'labjack_he3_pressure','faa_temperature',
                ]
    names = ['Upper stage', 'Charcoal', '3 K plate', 'He3 pot',
            'Magnet current', 'Magnet setpoint', 'He3 pressure', 'FAA',
            ]
    ylabels = ['Temperature (K)', 'Temperature (K)', 'Temperature (K)', 'Temperature (K)',
                'Current (mA)', 'Percent', press_unit ,'Temperature (K)']

    # xdata = dataset.get_parameter_data('time')
    plt.close('all')
    fig1, axes1 = plt.subplots(2,2, figsize = (10,10), sharex= True)
    fig2, axes2 = plt.subplots(2,2, figsize = (10,10), sharex= True)
    axes_list = [axes1[0][0], axes1[0][1], axes1[1][0], axes1[1][1],
                                            axes2[0][0], axes2[0][1], axes2[1][0], axes2[1][1]]
    qc.dataset.plot_by_id(run_id = run_id, axes= axes_list)
    dataset = qc.load_by_id(run_id=run_id)
    
    for i, ax in enumerate(axes_list):
        ax.set( ylabel = ylabels[i], title = names[i])
        # ax.grid(ls = ':', alpha = 0.75)

    fig1.suptitle (f'Experiment in 2pac ADR: Run {run_id} {dataset.completed_timestamp()=}')
    fig2.suptitle (f'Experiment in 2pac ADR: Run {run_id} {dataset.completed_timestamp()=}')
    plt.tight_layout()
    plt.show()


if __name__ == '__main__':
   main(run_id = 197, export_data = False)