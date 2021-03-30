#!/usr/bin/env python
"""Discovered events and visualizes each event from a storm. It loops through
 DMSP files and using an OMNIweb file it finds events and writes an output CSV
file of events, and plots to disk.

This uses case files generated by util_make_case_file.py.
"""

import argparse
import json
from matplotlib import MatplotlibDeprecationWarning
from matplotlib.colors import LogNorm
import pandas as pd
import numpy as np
import os
import pylab as plt
from termcolor import cprint
import warnings

import lib_search_dispersion 


def main():
    """Main routine of the program. Run with --help for description of arguments."""
    # Parse command line arguments
    parser = argparse.ArgumentParser()
    parser.add_argument('-i', metavar='CASE_FILE', required=True, help='Path to case file')
    parser.add_argument('--no-plot', action='store_true', help='Set to disable plotting')
    args = parser.parse_args()

    # Load case file ---------------------------------------------------------
    with open(args.i) as fh:
        case_file = json.load(fh)

    # Read OMNIWeb data all at once ------------------------------------------
    omniweb_fh = lib_search_dispersion.read_omniweb_files(case_file['OMNIWEB_FILES'])

    # Loop through files and call search_events() function
    # ------------------------------------------------------------------------    
    df_matches = []
    
    for i, dmsp_file in enumerate(case_file['DMSP_FILES']):
        cprint(f'Processing {i+1}/{len(case_file["DMSP_FILES"])} :: {dmsp_file}', 'green')
        
        df_match = search_events(
            dmsp_file=dmsp_file,
            omniweb_fh=omniweb_fh,
            outfolder=case_file['PLOT_OUTPUT'],
            no_plots=args.no_plot,
            reverse_effect=case_file['REVERSE_EFFECT'],
        )
        df_matches.append(df_match)

    df = pd.concat(df_matches).sort_values('start_time')

    # Write event list to console and output file ----------------------------
    cprint('Discovered events:', 'green')
    print(df.to_string(index=0))

    cprint('Writing event output (' + str(len(df.index)) + ' events) to '
           + case_file['EVENT_OUTPUT'], 'green')
    df.to_csv(case_file['EVENT_OUTPUT'], index=0)

    
def search_events(dmsp_file, omniweb_fh, outfolder=None, no_plots=False,
                  reverse_effect=False):
    """Search for events in a DMSP file.
    
    Args
      dmsp_file: Path to HDF5 DMSP file holding spectrogram data (daily)
      omniweb_fh: Loaded omniweb data in a dictionary
      outfolder: Path to write plots to (assuming no_plots=False)
      no_plots: Set to True to disable writing plots to disk
      reverse_effect: Search for effects in the opposite direction with a magnetic
        field set to the opposite of the coded threshold.
    Returns
      Pandas DataFrame holding events found in the file
    """
    # Do computation --------------------------------------------------
    from spacepy import pycdf
    try:
        dmsp_fh = lib_search_dispersion.read_dmsp_file(dmsp_file)
    except pycdf.CDFError:
        return

    dEicdt_smooth, Eic = lib_search_dispersion.estimate_log_Eic_smooth_derivative(dmsp_fh)

    df_match, integrand, _, _ = lib_search_dispersion.walk_and_integrate(
        dmsp_fh, omniweb_fh, dEicdt_smooth, Eic,
        lib_search_dispersion.INTERVAL_LENGTH,
        reverse_effect=reverse_effect, return_integrand=True
    )
    
    # Do plotting --------------------------------------------------
    for _, row_match in df_match.iterrows():
        i = dmsp_fh['t'].searchsorted(row_match.start_time)
        j = dmsp_fh['t'].searchsorted(row_match.end_time)

        delta_index = int(0.50 * (j - i))  # make plot 25% wider on each end
        i = max(i - delta_index, 0)
        j = min(j + delta_index, dmsp_fh['t'].size - 1)
        
        fig, axes = plt.subplots(2, 1, figsize=(18, 6), sharex=True)

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", MatplotlibDeprecationWarning)
            im = axes[0].pcolor(
                dmsp_fh['t'][i:j],
                np.log10(dmsp_fh['ch_energy']),
                dmsp_fh['ion_d_ener'][:, i:j], 
                norm=LogNorm(vmin=1e3, vmax=1e8), cmap='jet',
            )
        plt.colorbar(im, ax=axes[0]).set_label('Log Energy Flux')
        plt.colorbar(im, ax=axes[1]).set_label('')

        axes[0].plot(dmsp_fh['t'][i:j], Eic[i:j], 'b*-')
        axes[0].axhline(
            np.log10(lib_search_dispersion.MAX_ENERGY_ANALYZED),
            color='black', linestyle='dashed'
        )
        axes[0].invert_yaxis()
        axes[0].set_ylabel('Log Energy [eV] - Ions')
        
        time_length = row_match.end_time - row_match.start_time
        Bx, By, Bz = (row_match["Bx_mean"], row_match["By_mean"], row_match["Bz_mean"])
        title = (
            f'{row_match.start_time.isoformat()} - {row_match.end_time.isoformat()} ' +
            f'({time_length.total_seconds() / 60:.1f} minutes)\n' +
            ('Reverse Effect' if reverse_effect else 'Forward Effect') + ', ' 
            f'MLAT = ({dmsp_fh["mlat"][i]:.1f} deg to {dmsp_fh["mlat"][j]:.1f} deg), ' +
            "$\\vec{B}$" + f' = ({Bx:.2f}, {By:.2f}, {Bz:.2f}) nT'
        )
        axes[0].set_title(title)
                            
        axes[1].fill_between(dmsp_fh['t'][i:j], 0, integrand[i:j])
        axes[1].axhline(0, color='black', linestyle='dashed')
        axes[1].set_ylim([-.25, .25])
        axes[1].set_ylabel('D(t) [eV/s]')
        
        if not no_plots:
            out_name = outfolder + '/'
            out_name += f'{os.path.basename(dmsp_file)}_'
            out_name += f"{row_match.start_time.isoformat()}_"
            out_name += f"{row_match.end_time.isoformat()}.png"

            os.makedirs(outfolder, exist_ok=True)
            plt.savefig(out_name)
            plt.close()
            
            cprint('Wrote plot ' + out_name, 'green')
            
            df_match['file'] = dmsp_file
        
    return df_match


if __name__ == '__main__':
    main()
