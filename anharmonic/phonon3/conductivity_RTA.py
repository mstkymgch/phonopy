import numpy as np
import phonopy.structure.spglib as spg
from phonopy.harmonic.force_constants import similarity_transformation
from phonopy.phonon.group_velocity import get_group_velocity
from phonopy.units import Kb, THzToEv, EV, THz, Angstrom
from phonopy.phonon.thermal_properties import mode_cv
from anharmonic.file_IO import write_kappa_to_hdf5
from anharmonic.phonon3.triplets import get_grid_address, reduce_grid_points, get_ir_grid_points, from_coarse_to_dense_grid_points
from anharmonic.phonon3.imag_self_energy import ImagSelfEnergy

unit_to_WmK = ((THz * Angstrom) ** 2 / (Angstrom ** 3) * EV / THz /
               (2 * np.pi)) # 2pi comes from definition of lifetime.

class conductivity_RTA:
    def __init__(self,
                 interaction,
                 sigmas=[0.1],
                 t_max=1500,
                 t_min=0,
                 t_step=10,
                 mesh_divisors=None,
                 coarse_mesh_shifts=None,
                 no_kappa_stars=False,
                 gv_delta_q=1e-4, # finite difference for group veolocity
                 log_level=0,
                 filename=None):
        self._pp = interaction
        self._ise = ImagSelfEnergy(self._pp)

        self._sigmas = sigmas
        self._t_max = t_max
        self._t_min = t_min
        self._t_step = t_step
        self._no_kappa_stars = no_kappa_stars
        self._gv_delta_q = gv_delta_q
        self._log_level = log_level
        self._filename = filename

        self._temperatures = np.arange(self._t_min,
                                       self._t_max + float(self._t_step) / 2,
                                       self._t_step)
        self._primitive = self._pp.get_primitive()
        self._dynamical_matrix = self._pp.get_dynamical_matrix()
        self._frequency_factor_to_THz = self._pp.get_frequency_factor_to_THz()
        self._cutoff_frequency = self._pp.get_cutoff_frequency()
        self._grid_points = None
        self._grid_weights = None
        self._grid_address = None

        self._point_operations = get_pointgroup_operations(
            self._pp.get_point_group_operations())
        self._gamma = None
        self._read_gamma = False
        self._frequencies = None
        self._cv = None
        self._gv = None

        self._mesh = None
        self._mesh_divisors = None
        self._coarse_mesh = None
        self._coarse_mesh_shifts = None
        self._set_mesh_numbers(mesh_divisors=mesh_divisors,
                               coarse_mesh_shifts=coarse_mesh_shifts)
        volume = self._primitive.get_volume()
        self._conversion_factor = unit_to_WmK / volume
        self._sum_num_kstar = 0

    def get_mesh_divisors(self):
        return self._mesh_divisors

    def get_mesh_numbers(self):
        return self._mesh

    def get_group_velocities(self):
        return self._gv

    def get_mode_heat_capacities(self):
        return self._cv

    def get_frequencies(self):
        return self._frequencies
        
    def set_grid_points(self, grid_points=None):
        if grid_points is not None: # Specify grid points
            self._grid_address = get_grid_address(self._mesh)
            self._grid_points = reduce_grid_points(
                self._mesh_divisors,
                self._grid_address,
                grid_points,
                coarse_mesh_shifts=self._coarse_mesh_shifts)
        elif self._no_kappa_stars: # All grid points
            self._grid_address = get_grid_address(self._mesh)
            coarse_grid_address = get_grid_address(self._coarse_mesh)
            coarse_grid_points = np.arange(np.prod(self._coarse_mesh),
                                           dtype='intc')
            self._grid_points = from_coarse_to_dense_grid_points(
                self._mesh,
                self._mesh_divisors,
                coarse_grid_points,
                coarse_grid_address,
                coarse_mesh_shifts=self._coarse_mesh_shifts)
            self._grid_weights = np.ones(len(self._grid_points), dtype='intc')
        else: # Automatic sampling
            if self._coarse_mesh_shifts is None:
                mesh_shifts = [False, False, False]
            else:
                mesh_shifts = self._coarse_mesh_shifts
            (coarse_grid_points,
             coarse_grid_weights,
             coarse_grid_address) = get_ir_grid_points(
                self._coarse_mesh,
                self._primitive,
                mesh_shifts=mesh_shifts)
            self._grid_points = from_coarse_to_dense_grid_points(
                self._mesh,
                self._mesh_divisors,
                coarse_grid_points,
                coarse_grid_address,
                coarse_mesh_shifts=self._coarse_mesh_shifts)
            self._grid_address = get_grid_address(self._mesh)
            self._grid_weights = coarse_grid_weights

            assert self._grid_weights.sum() == np.prod(self._mesh /
                                                       self._mesh_divisors)

    def get_qpoints(self):
        qpoints = np.double([self._grid_address[gp].astype(float) / self._mesh
                             for gp in self._grid_points])
        return qpoints
            
    def get_grid_points(self):
        return self._grid_points

    def get_grid_weights(self):
        return self._grid_weights
            
    def set_temperatures(self, temperatures):
        self._temperatures = temperatures

    def get_temperatures(self):
        return self._temperatures

    def set_gamma(self, gamma):
        self._gamma = gamma
        self._read_gamma = True

    def get_gamma(self):
        return self._gamma
        
    def get_kappa(self):
        return self._kappa / self._sum_num_kstar

    def calculate_kappa(self,
                        write_amplitude=False,
                        read_amplitude=False,
                        write_gamma=False):
        self._allocate_values()
        num_band = self._primitive.get_number_of_atoms()
        for i, grid_point in enumerate(self._grid_points):
            self._qpoint = (self._grid_address[grid_point].astype('double') /
                            self._mesh)
            
            if self._log_level:
                print ("===================== Grid point %d (%d/%d) "
                       "=====================" %
                       (grid_point, i + 1, len(self._grid_points)))
                print "q-point: (%5.2f %5.2f %5.2f)" % tuple(self._qpoint)

            if self._read_gamma:
                self._frequencies[i] = self._get_phonon_c()
            else:
                if self._log_level > 0:
                    print "Number of triplets:",

                self._ise.set_grid_point(grid_point)
                
                if self._log_level > 0:
                    print len(self._pp.get_triplets_at_q()[0])
                    print "Calculating interaction"
                self._ise.run_interaction()
                self._frequencies[i] = self._ise.get_phonon_at_grid_point()[0]
                self._set_gamma_at_sigmas(i)

            self._set_kappa_at_sigmas(i)

            if write_gamma:
                self._write_gamma(i, grid_point)

    def _allocate_values(self):
        num_freqs = self._primitive.get_number_of_atoms() * 3
        self._kappa = np.zeros((len(self._sigmas),
                                len(self._grid_points),
                                len(self._temperatures),
                                num_freqs,
                                6), dtype='double')
        if not self._read_gamma:
            self._gamma = np.zeros((len(self._sigmas),
                                    len(self._grid_points),
                                    len(self._temperatures),
                                    num_freqs), dtype='double')
        self._gv = np.zeros((len(self._grid_points),
                             num_freqs,
                             3), dtype='double')
        self._cv = np.zeros((len(self._grid_points),
                             len(self._temperatures),
                             num_freqs), dtype='double')

        self._frequencies = np.zeros((len(self._grid_points),
                                      num_freqs), dtype='double')
        
    def _set_gamma_at_sigmas(self, i):
        freqs = self._frequencies[i]
        for j, sigma in enumerate(self._sigmas):
            if self._log_level > 0:
                print "Calculating Gamma with sigma=%s" % sigma
            self._ise.set_sigma(sigma)
            for k, t in enumerate(self._temperatures):
                self._ise.set_temperature(t)
                self._ise.run()
                gamma_at_gp = np.where(freqs > self._cutoff_frequency,
                                       self._ise.get_imag_self_energy(), -1)
                self._gamma[j, i, k] = gamma_at_gp
    
    def _set_kappa_at_sigmas(self, i):
        freqs = self._frequencies[i]
        
        # Group velocity [num_freqs, 3]
        gv = get_group_velocity(
            self._qpoint,
            self._dynamical_matrix,
            q_length=self._gv_delta_q,
            frequency_factor_to_THz=self._frequency_factor_to_THz)
        self._gv[i] = gv
        
        # Heat capacity [num_temps, num_freqs]
        cv = self._get_cv(freqs)
        self._cv[i] = cv

        # Outer product of group velocities (v x v) [num_k*, num_freqs, 3, 3]
        gv_by_gv_tensor = self._get_gv_by_gv(gv, i)
        self._sum_num_kstar += len(gv_by_gv_tensor)

        # Sum all vxv at k*
        gv_sum2 = np.zeros((6, len(freqs)), dtype='double')
        for j, vxv in enumerate(
            ([0, 0], [1, 1], [2, 2], [1, 2], [0, 2], [0, 1])):
            gv_sum2[j] = gv_by_gv_tensor[:, :, vxv[0], vxv[1]].sum(axis=0)

        # Kappa
        for j, sigma in enumerate(self._sigmas):
            for k in range(len(self._temperatures)):
                for l in range(len(freqs)):
                    if self._gamma[j, i, k, l] > 1e-12:
                        self._kappa[j, i, k, l, :] = (
                            gv_sum2[:, l] * cv[k, l] /
                            (self._gamma[j, i, k, l] * 2) *
                            self._conversion_factor)

    def _get_gv_by_gv(self, gv, i):
        grid_point = self._grid_points[i]
        rotations = self._get_rotations_for_star(i)
        gv2_tensor = []
        rec_lat = np.linalg.inv(self._primitive.get_cell())
        rotations_cartesian = [similarity_transformation(rec_lat, r)
                               for r in rotations]
        for rot_c in rotations_cartesian:
            gv2_tensor.append([np.outer(gv_rot, gv_rot)
                               for gv_rot in np.dot(rot_c, gv.T).T])

        if self._log_level:
            self._show_log(grid_point,
                           self._frequencies[i],
                           gv,
                           rotations,
                           rotations_cartesian)

        return np.array(gv2_tensor)
    
    def _get_cv(self, freqs):
        cv = np.zeros((len(self._temperatures), len(freqs)), dtype='double')
        # for i, t in enumerate(self._temperatures):
        #     if t > 0:
        #         for j, f in enumerate(freqs):
        #             if f > self._cutoff_frequency:
        #                 cv[i, j] = mode_cv(t, f * THzToEv) # eV/K

        # T/freq has to be large enough to avoid divergence.
        # Otherwise just set 0.
        for i, f in enumerate(freqs):
            finite_t = (self._temperatures > f / 100)
            if f > self._cutoff_frequency:
                cv[:, i] = np.where(
                    finite_t, mode_cv(
                        np.where(finite_t, self._temperatures, 10000),
                        f * THzToEv), 0)
        return cv


    def _get_rotations_for_star(self, i):
        if self._no_kappa_stars:
            rotations = [np.eye(3, dtype=int)]
        else:
            grid_point = self._grid_points[i]
            orig_address = self._grid_address[grid_point]
            orbits = []
            rotations = []
            for rot in self._point_operations:
                rot_address = np.dot(rot, orig_address) % self._mesh
                in_orbits = False
                for orbit in orbits:
                    if (rot_address == orbit).all():
                        in_orbits = True
                        break
                if not in_orbits:
                    orbits.append(rot_address)
                    rotations.append(rot)
    
            # check if the number of rotations is correct.
            if self._grid_weights is not None:
                if len(rotations) != self._grid_weights[i]:
                    if self._log_level:
                        print "*" * 33  + "Warning" + "*" * 33
                        print (" Number of elements in k* is unequal "
                               "to number of equivalent grid-points.")
                        print "*" * 73
                # assert len(rotations) == self._grid_weights[i], \
                #     "Num rotations %d, weight %d" % (
                #     len(rotations), self._grid_weights[i])

        return rotations

    def _set_mesh_numbers(self, mesh_divisors=None, coarse_mesh_shifts=None):
        self._mesh = self._pp.get_mesh_numbers()

        if mesh_divisors is None:
            self._mesh_divisors = np.intc([1, 1, 1])
        else:
            self._mesh_divisors = []
            for i, (m, n) in enumerate(zip(self._mesh, mesh_divisors)):
                if m % n == 0:
                    self._mesh_divisors.append(n)
                else:
                    self._mesh_divisors.append(1)
                    print ("Mesh number %d for the " +
                           ["first", "second", "third"][i] + 
                           " axis is not dividable by divisor %d.") % (m, n)
            self._mesh_divisors = np.intc(self._mesh_divisors)
            if coarse_mesh_shifts is None:
                self._coarse_mesh_shifts = [False, False, False]
            else:
                self._coarse_mesh_shifts = coarse_mesh_shifts
            for i in range(3):
                if (self._coarse_mesh_shifts[i] and
                    (self._mesh_divisors[i] % 2 != 0)):
                    print ("Coarse grid along " +
                           ["first", "second", "third"][i] + 
                           " axis can not be shifted. Set False.")
                    self._coarse_mesh_shifts[i] = False

        self._coarse_mesh = self._mesh / self._mesh_divisors

        if self._log_level:
            print ("Lifetime sampling mesh: [ %d %d %d ]" %
                   tuple(self._mesh / self._mesh_divisors))

    def _get_phonon_c(self):
        import anharmonic._phono3py as phono3c

        dm = self._dynamical_matrix
        svecs, multiplicity = dm.get_shortest_vectors()
        masses = np.double(dm.get_primitive().get_masses())
        rec_lattice = np.double(
            np.linalg.inv(dm.get_primitive().get_cell())).copy()
        if dm.is_nac():
            born = dm.get_born_effective_charges()
            nac_factor = dm.get_nac_factor()
            dielectric = dm.get_dielectric_constant()
        else:
            born = None
            nac_factor = 0
            dielectric = None
        uplo = self._pp.get_lapack_zheev_uplo()
        num_freqs = len(masses) * 3
        frequencies = np.zeros(num_freqs, dtype='double')
        eigenvectors = np.zeros((num_freqs, num_freqs), dtype='complex128')

        phono3c.phonon(frequencies,
                       eigenvectors,
                       np.double(self._qpoint),
                       dm.get_force_constants(),
                       svecs,
                       multiplicity,
                       masses,
                       dm.get_primitive_to_supercell_map(),
                       dm.get_supercell_to_primitive_map(),
                       self._frequency_factor_to_THz,
                       born,
                       dielectric,
                       rec_lattice,
                       None,
                       nac_factor,
                       uplo)
        # dm.set_dynamical_matrix(self._qpoint)
        # dynmat = dm.get_dynamical_matrix()
        # eigvals = np.linalg.eigvalsh(dynmat).real
        # frequencies = (np.sqrt(np.abs(eigvals)) * np.sign(eigvals) *
        #                self._frequency_factor_to_THz)

        return frequencies

    def _show_log(self,
                  grid_point,
                  frequencies,
                  group_velocity,
                  rotations,
                  rotations_cartesian):
        print "----- Partial kappa at grid address %d -----" % grid_point
        print "Frequency, projected group velocity (x, y, z), norm at k-stars",
        if self._gv_delta_q is None:
            print
        else:
            print " (dq=%3.1e)" % self._gv_delta_q
        q = self._grid_address[grid_point].astype(float) / self._mesh
        for i, (rot, rot_c) in enumerate(zip(rotations, rotations_cartesian)):
            q_rot = np.dot(rot, q)
            q_rot -= np.rint(q_rot)
            print " k*%-2d (%5.2f %5.2f %5.2f)" % ((i + 1,) + tuple(q_rot))
            for f, v in zip(frequencies, np.dot(rot_c, group_velocity.T).T):
                print "%8.3f   (%8.3f %8.3f %8.3f) %8.3f" % (
                    f, v[0], v[1], v[2], np.linalg.norm(v))

        print

    def _write_gamma(self, i, grid_point):
        for j, sigma in enumerate(self._sigmas):
            write_kappa_to_hdf5(
                self._gamma[j, i],
                self._temperatures,
                self._mesh,
                frequency=self._frequencies[i],
                group_velocity=self._gv[i],
                heat_capacity=self._cv[i],
                mesh_divisors=self._mesh_divisors,
                grid_point=grid_point,
                sigma=sigma,
                filename=self._filename)

        
def get_pointgroup_operations(point_operations_real):
    exist_r_inv = False
    for rot in point_operations_real:
        if (rot + np.eye(3, dtype='intc') == 0).all():
            exist_r_inv = True
            break

    point_operations = [rot.T for rot in point_operations_real]
    
    if not exist_r_inv:
        point_operations += [-rot.T for rot in point_operations_real]
        
    return np.array(point_operations)

            
        
if __name__ == '__main__':
    import sys
    import h5py

    def read_kappa(filename):
        vals = []
        for line in open(filename):
            if line.strip()[0] == '#':
                continue
            vals.append([float(x) for x in line.split()])
        vals = np.array(vals)
        return vals[:, 0], vals[:, 1]

    def sum_partial_kappa(filenames):
        temps, kappa = read_kappa(filenames[0])
        sum_kappa = kappa.copy()
        for filename in filenames[1:]:
            temps, kappa = parse_kappa(filename)
            sum_kappa += kappa
        return temps, sum_kappa
    
    def sum_partial_kappa_hdf5(filenames):
        f = h5py.File(filenames[0], 'r')
        kappas = f['kappas'][:]
        temps = f['temperatures'][:]
        for filename in filenames[1:]:
            f = h5py.File(filename, 'r')
            kappas += f['kappas'][:]
        return temps, kappas

    temps, kappa = sum_partial_kappa(sys.argv[1:])
    for t, k in zip(temps, kappa):
        print "%8.2f %.5f" % (t, k)
    # temps, kappa = sum_partial_kappa_hdf5(sys.argv[1:])
    # for t, k in zip(temps, kappa.sum(axis=1)):
    #     print "%8.2f %.5f" % (t, k)


