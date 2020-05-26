# Base imports
import sys, os, time
sys.path.insert(0, '/app/tti')
from argparse import ArgumentParser
import numpy as np

# Devito imports
from devito.logger import info  

# tti imports from docker image
from model import *
from sources import *
from tti_propagators import *

# segy
import segyio as so

# Interpolation and filtering utils
from scipy import interpolate
from utils import butter_bandpass_filter, butter_lowpass_filter

# Azure utilities
from AzureUtilities import read_h5_model, write_h5_model, process_summaries, read_coordinates

def timer(start, message):
    end = time.time()
    hours, rem = divmod(end-start, 3600)
    minutes, seconds = divmod(rem, 60)
    info('{}: {:d}:{:02d}:{:02d}'.format(message, int(hours), int(minutes), int(seconds)))

""
# Process summary of performance info
def process_summary(summary):
    kernel_runtime = 0  # total runtime
    gflopss = 0 # total no. of "FLOPS"
    gpointss = 0  
    oi = 0
    for key in summary:
        kernel_runtime += summary[key].time
        gflopss += summary[key].gflopss
        gpointss += summary[key].gpointss
        oi += summary[key].oi
    oi = oi / len(summary.keys())   # Average operational intensity
    return [kernel_runtime, gflopss, gpointss, oi]
""
# Time resampling for shot records
def resample(rec, num):
    start, stop = rec._time_range.start, rec._time_range.stop
    dt0 = rec._time_range.step
    new_time_range = TimeAxis(start=start, stop=stop, num=num)
    dt = new_time_range.step
    to_interp = np.asarray(rec.data)
    data = np.zeros((num, to_interp.shape[1]))
    for i in range(to_interp.shape[1]):
        tck = interpolate.splrep(rec._time_range.time_values, to_interp[:, i], k=3)
        data[:, i] = interpolate.splev(new_time_range.time_values, tck)
    coords_loc = np.asarray(rec.coordinates.data)
    # Return new object
    return data, coords_loc

""
# Segy writer for shot records
def segy_write(data, sourceX, sourceZ, groupX, groupZ, dt, filename, sourceY=None,
               groupY=None, elevScalar=-1000, coordScalar=-1000):
    nt = data.shape[0]
    nxrec = len(groupX)
    if sourceY is None and groupY is None:
        sourceY = np.zeros(1, dtype='int')
        groupY = np.zeros(nxrec, dtype='int')
    
    # Create spec object
    spec = so.spec()
    spec.ilines = np.arange(nxrec)    # dummy trace count
    spec.xlines = np.zeros(1, dtype='int')  # assume coordinates are already vectorized for 3D
    spec.samples = range(nt)
    spec.format=1
    spec.sorting=1
    with so.create(filename, spec) as segyfile:
        for i in range(nxrec):
            segyfile.header[i] = {
                so.su.tracl : i+1,
                so.su.tracr : i+1,
                so.su.fldr : 1,
                so.su.tracf : i+1,
                so.su.sx : int(np.round(sourceX[0] * np.abs(coordScalar))),
                so.su.sy : int(np.round(sourceY[0] * np.abs(coordScalar))),
                so.su.selev: int(np.round(sourceZ[0] * np.abs(elevScalar))),
                so.su.gx : int(np.round(groupX[i] * np.abs(coordScalar))),
                so.su.gy : int(np.round(groupY[i] * np.abs(coordScalar))),
                so.su.gelev : int(np.round(groupZ[i] * np.abs(elevScalar))),
                so.su.dt : int(dt*1e3),
                so.su.scalel : int(elevScalar),
                so.su.scalco : int(coordScalar)
            }
            segyfile.trace[i] = data[:, i]
        segyfile.dt=int(dt*1e3)

""
t0 = time.time()

####### Filter arguments
description = ("3D modeling on tti overdone")
parser = ArgumentParser(description=description)
parser.add_argument("--id",  dest='shot_id', default=1, type=int,
                    help="Shot number")
parser.add_argument("--recloc",  dest='recloc', default="", type=str,
                    help="Path to results directory in blob")
parser.add_argument("--modelloc",  dest='modelloc', default="", type=str,
                    help="Path to model directory in blob")
parser.add_argument("--geomloc",  dest='geomloc', default="", type=str,
                    help="Path to geometry directory in blob")
parser.add_argument("--fs",  dest='freesurf', default=False, action='store_true',
                    help="Freesurface")
args = parser.parse_args()

# Get inputs
shot_id = args.shot_id
recloc = args.recloc
modelloc = args.modelloc
geomloc = args.geomloc
freesurf = args.freesurf

# Some parameters
space_order = 12
nbpml = 40
timer(t0, 'Args process')
t0 = time.time()

""
# Read models
rho = read_h5_model(modelloc + 'rho_with_salt.h5')
epsilon = read_h5_model(modelloc + 'epsilon_with_salt.h5')
delta = read_h5_model(modelloc + 'delta_with_salt.h5')
theta = read_h5_model(modelloc + 'theta_with_salt.h5')
phi = read_h5_model(modelloc + 'phi_with_salt.h5')
vp = read_h5_model(modelloc + 'vp_fine_with_salt.h5')
shape = (801, 801, 267)
origin = (0.0, 0.0, 0.0)
spacing = (12.5, 12.5, 12.5)
model = Model(shape=shape, origin=origin, spacing=spacing, vp=vp, space_order=space_order,
              epsilon=epsilon, delta=delta, theta=theta, phi=phi, rho=rho, nbpml=nbpml)


# Read coordinates
file_idx = geomloc + 'source_indices.npy'
file_src = geomloc + 'src_coordinates.h5'
file_rec = geomloc + 'rec_coordinates.h5'
xsrc_full, ysrc_full, zsrc_full = read_coordinates(file_src)
xrec_full, yrec_full, zrec_full = read_coordinates(file_rec)
xsrc = xsrc_full[shot_id]; ysrc = ysrc_full[shot_id]; zsrc = zsrc_full[shot_id]

# Set up coordinates as nrec x 3 numpy array
rec_coordinates = np.concatenate((xrec_full.reshape(-1,1), yrec_full.reshape(-1,1), 
    zrec_full.reshape(-1,1)), axis=1)
nrec = rec_coordinates.shape[0]

""
# Get MPI info
comm = model.grid.distributor.comm
rank =  comm.Get_rank()
size =  comm.size
info("Min value in vp is %s " % (np.min(model.vp.data[:])))
timer(t0, 'Read segy models')
t0 = time.time()

#########################################################################################
# Model a 2D shot

# Time axis
tstart = 0.
tn = 1000.
dt = model.critical_dt
f0 = 0.020
time_axis = TimeAxis(start=tstart, step=dt, stop=tn)

""
# Source geometry
src_coords = np.empty((1, len(spacing)))
src_coords[0, 0] = xsrc
src_coords[0, 1] = ysrc
src_coords[0, 2] = zsrc

src = RickerSource(name='src', grid=model.grid, f0=f0, time_range=time_axis, npoint=1)
src.coordinates.data[0, :] = src_coords[:]

wavelet = np.concatenate((np.load("%swavelet.npy"%geomloc), np.zeros((100,))))
twave = [i*1.2 for i in range(wavelet.shape[0])]
tnew = [i*dt for i in range(int(1 + (twave[-1]-tstart) / dt))]
fq = interpolate.interp1d(twave, wavelet, kind='linear')
q_custom = np.zeros((time_axis.num, 1))
q_custom[:len(tnew), 0] = fq(tnew)
q_custom[:, 0] = butter_bandpass_filter(q_custom[:, 0], .005, .030, 1/dt)
q_custom[:, 0] = 1e1 * q_custom[:, 0] / np.max(q_custom[:, 0])
src.data[:, 0] = q_custom[:, 0]

timer(t0, 'Setup geometry')
t0 = time.time()

""
# Propagator
tti = TTIPropagators(model, space_order=space_order)

""
# Data
info("Starting forward modeling")
tstart = time.time()
d_obs, u, v, summary1 = tti.forward(src, rec_coordinates, autotune=('aggressive', 'runtime'))
tend = time.time()
timer(t0, 'Run forward')
t0 = time.time()

""

#######################################################################################
# Check output

info("Nan values : %s" % np.any(np.isnan(d_obs.data[:])))
info("Max value in rec : %s" % np.max(d_obs.data[:]))
info("Max values in u, v : (%s, %s)" % (np.max(u.data[:]), np.max(v.data[:])))
info("saving shot records %srecloc%s%s" % (recloc, rank, shot_id))

# Resample
data_loc, coord_loc = resample(d_obs, 501)

#Save local
np.save("%srecloc%s%s.npy"% (recloc, rank, shot_id), data_loc)
np.save("%scoordloc%s%s.npy"% (recloc, rank, shot_id), coord_loc)


timer(t0, 'Locally saved')
t0 = time.time()

#######################################################################################
# Merge output

if rank == 0:
    data = np.load("%srecloc0%s.npy" % (recloc, shot_id))
    coords = np.load("%scoordloc0%s.npy" % (recloc, shot_id))

    for i in range(1, size):
        # Wait until all files are ready
        while True:
            try:
                datai = np.load("%srecloc%s%s.npy" %  (recloc, i, shot_id))
                coordsi = np.load("%scoordloc%s%s.npy" %  (recloc, i, shot_id))
                assert datai.shape[0]  == data.shape[0]
                assert coordsi.shape[1] == coords.shape[1]
            except:
                info("File not ready")
                time.sleep(10)
                info("Waited a bit trying again")
            else:
                info("File for rank %s found" % i)
                break

        coords = np.vstack((coords, coordsi))
        data = np.hstack((data, datai))
        os.system("rm -f %srecloc%s%s.npy %scoordloc%s%s.npy" % (recloc, i, shot_id, recloc, i, shot_id))

    # Remove duplicates
    coords, inds = np.unique(coords, axis=0, return_index=True)
    data = data[:, inds]
    assert data.shape[1] == nrec

    # Save full shot record in segy
    info("%s, %s", data.shape, nrec)
    info("Writing shot record of size (%s, %s) to segy file, maximum value is %s" % (data.shape[0], data.shape[1], np.max(data)))
    os.system("rm -f %srecloc%s%s.npy %scoordloc%s%s.npy" % (recloc, 0, shot_id, recloc, 0, shot_id))
    segy_write(data, [src_coords[0,0]], [src_coords[0,2]],
               coords[:, 0], coords[:, -1],
               2.0,  "%srec%s.segy" % (recloc, shot_id),
               sourceY=[src_coords[0,1]], groupY=coords[:, 1])

    # Save performance info
    summary = process_summary(summary1)
    summary.insert(0, tend - tstart)
    summary = np.array(summary)
    summary.dump('summary_rec' + str(recloc) + '_shot_' + str(shot_id) + '.npy')

if rank == 0:
    info("All done with saving")