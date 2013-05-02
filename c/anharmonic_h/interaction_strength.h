#ifndef __interaction_strength_H__
#define __interaction_strength_H__

#include <lapacke.h>
#include "alloc_array.h"

int get_interaction_strength(double *amps,
			     double *freqs,
			     const int num_triplets,
			     const int num_grid_points,
			     const double *q0,
			     const double *q1s,
			     const double *q2s,
			     const double *fc2,
			     const double *fc3,
			     const double *masses_fc2,
			     const double *masses_fc3,
			     const Array1D *p2s_fc2,
			     const Array1D *s2p_fc2,
			     const Array1D *p2s_fc3,
			     const Array1D *s2p_fc3,
			     const Array2D *multi_fc2,
			     const ShortestVecs *svecs_fc2,
			     const Array2D *multi_fc3,
			     const ShortestVecs *svecs_fc3,
			     const Array1D *band_indices,
			     const double *born,
			     const double *dielectric,
			     const double *reciprocal_lattice,
			     const double *q_direction,
			     const double nac_factor,
			     const double freq_unit_factor,
			     const double cutoff_frequency,
			     const int is_symmetrize_fc3_q,
			     const int r2q_TI_index,
			     const char uplo);
int get_triplet_interaction_strength(double *amps,
				     const double *fc3,
				     const double *q_vecs,
				     const lapack_complex_double* eigvecs,
				     const double *freqs,
				     const double *masses,
				     const Array1D *p2s,
				     const Array1D *s2p,
				     const Array2D *multi,
				     const ShortestVecs *svecs,
				     const Array1D *band_indices,
				     const double cutoff_frequency,
				     const int is_symmetrize_fc3_q,
				     const int r2q_TI_index);
int get_fc3_realspace(lapack_complex_double* fc3_real,
		      const ShortestVecs * svecs,
		      const Array2D * multi,
		      const double* q_triplet,
		      const int * s2p,
		      const lapack_complex_double* fc3_rec);
int get_fc3_reciprocal(lapack_complex_double* fc3_q,
		       const ShortestVecs * svecs,
		       const Array2D * multi,
		       const DArray2D * q,
		       const Array1D * p2s,
		       const Array1D * s2p,
		       const double* fc3,
		       const int r2q_TI_index);
int get_fc3_sum_in_supercell(lapack_complex_double fc3_q[3][3][3],
			     const int i1,
			     const int i2,
			     const int i3,
			     const ShortestVecs * svecs,
			     const Array2D * multi,
			     const DArray2D * q,
			     const Array1D * s2p,
			     const Array1D * p2s,
			     const double* fc3,
			     const int r2q_TI_index);
double get_sum_in_primivie(const lapack_complex_double *fc3,
			   const lapack_complex_double *e1,
			   const lapack_complex_double *e2,
			   const lapack_complex_double *e3,
			   const int num_atom,
			   const double *m);

#endif
