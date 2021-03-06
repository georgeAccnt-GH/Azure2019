import sys, os
# Add path to TTI module
sys.path.insert(0, os.getcwd()[:-8] + '/src/AzureBatch/docker/tti_image/tti')
import numpy as np
import matplotlib.pyplot as plt
from model import Model
from sources import RickerSource, TimeAxis, Receiver
from tti_propagators import TTIPropagators
import segyio as so
from scipy import interpolate, ndimage
from AzureUtilities import read_h5_model, write_h5_model, butter_bandpass_filter, butter_lowpass_filter, resample, process_summaries, read_coordinates, save_rec, restrict_model_to_receiver_grid, extent_gradient
from scipy import interpolate, ndimage

#########################################################################################

def limit_receiver_grid(xsrc, xrec, zrec, maxoffset):

    xmin = np.max([xsrc - maxoffset, 12.5])
    xmax = np.min([xsrc + maxoffset, 9987.5])

    print('xrange: ', xmin, ' to ', xmax)

    xnew = []
    znew = []

    for j in range(len(xrec)):
        if xrec[j] >= xmin and xrec[j] <= xmax:
            xnew.append(xrec[j])
            znew.append(zrec[j])

    xnew = np.array(xnew)
    znew = np.array(znew)

    return xnew, znew

#########################################################################################

# Read models
rho = read_h5_model('../data/models/rho_with_salt.h5')
epsilon = read_h5_model('../data/models/epsilon_with_salt.h5')
delta = read_h5_model('../data/models/delta_with_salt.h5')
theta = read_h5_model('../data/models/theta_with_salt.h5')
m0 = read_h5_model('../data/models/migration_velocity.h5')
dm = read_h5_model('../data/models/perturbation.h5')

rho = rho[200,:,:]
epsilon = epsilon[200,:,:]
delta = delta[200,:,:]
theta = theta[200,:,:]
m0 = m0[200,:,:]
dm = dm[200,:,:]

# Set dm to zero in water
#theta[:,:] = 0.
dm[:,0:29] = 0.

shape_full = (801, 267)
origin_full = (0.0, 0.0)
spacing = (12.5, 12.5)
so = 12

# Read source coordinates
shot_no = 0
file_idx = '../data/geometry/source_indices.npy'
file_src = '../data/geometry/src_coordinates.h5'
xsrc_full, ysrc_full, zsrc_full = read_coordinates(file_src)
idx = np.load(file_idx)[shot_no]
#xsrc = xsrc_full[idx]; zsrc = zsrc_full[idx]
xsrc = 7000.
zsrc = 300

# Receivers coordinates
nrec = 799
xrec_full = np.array(np.linspace(12.5, 9987.5, nrec))
zrec_full = np.array(np.linspace(6., 6., nrec))

# Limit receiver grid
buffersize = 500    # in m
maxoffset = 3787.5  # in m
xrec, zrec = limit_receiver_grid(xsrc, xrec_full, zrec_full, maxoffset)

# Restrict models
print('Original shape: ', shape_full, ' and origin ', origin_full)
m0, shape, origin = restrict_model_to_receiver_grid(xsrc, xrec, m0, spacing, origin_full, buffer_size=buffersize)
rho = restrict_model_to_receiver_grid(xsrc, xrec, rho, spacing, origin_full, buffer_size=buffersize)[0]
epsilon = restrict_model_to_receiver_grid(xsrc, xrec, epsilon, spacing, origin_full, buffer_size=buffersize)[0]
delta = restrict_model_to_receiver_grid(xsrc, xrec, delta, spacing, origin_full, buffer_size=buffersize)[0]
theta = restrict_model_to_receiver_grid(xsrc, xrec, theta, spacing, origin_full, buffer_size=buffersize)[0]
dm = restrict_model_to_receiver_grid(xsrc, xrec, dm, spacing, origin_full, buffer_size=buffersize)[0]
print('New shape: ', shape, ' and origin ', origin)

# Model structure
model = Model(shape=shape, origin=origin, spacing=spacing, vp=np.sqrt(1/m0), space_order=so,
              epsilon=epsilon, delta=delta, theta=theta, rho=rho, nbpml=40, dm=dm, dt=0.64)

#########################################################################################

# Time axis
t0 = 0.
tn = 2000.
dt_shot = 4.
nt = int(tn/dt_shot + 1)
dt = 0.64#model.critical_dt*.9
time = TimeAxis(start=t0, step=dt, stop=tn)

#########################################################################################

# Coordinates
src = RickerSource(name='src', grid=model.grid, f0=.015, time_range=time, npoint=1)
src.coordinates.data[0, 0] = xsrc
src.coordinates.data[0, 1] = zsrc

nrec = len(xrec)
rec_coords = np.empty((nrec, 2))
rec_coords[:, 0] = xrec
rec_coords[:, 1] = zrec

#########################################################################################

# Devito operator
tti = TTIPropagators(model, space_order=so)

# Shot and gradient
d_obs, u0, v0, summary1 = tti.born(src, rec_coords, save=True, sub=(12, 1))
grad, summary2 = tti.gradient(d_obs, u0, v0, sub=(12, 1), isic=True)
grad.data[:,0:66] = 0   # mute water column

# Remove pml and pad
rtm = grad.data[model.nbpml:-model.nbpml, model.nbpml:-model.nbpml]  # remove padding
rtm = extent_gradient(shape_full, origin_full, shape, origin, spacing, rtm)
plt.figure(); plt.imshow(d_obs.data, vmin=-.1, vmax=.1, cmap='gray', aspect='auto')
plt.figure(); plt.imshow(np.transpose(rtm), vmin=-2e-2, vmax=2e-2, cmap='gray', aspect='auto')
plt.show()
