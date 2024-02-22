'''
Main functions for estimating SparCC
'''
from glob import glob
from typing import List,Any

import warnings
import logging
import numpy as np

from .core_methods import to_fractions
from .compositional_methods import run_clr,variation_mat

try:
    from scipy.stats import nanmedian
except ImportError:
    from numpy import nanmedian


def Mesh(a:int):
    '''simple version of : 
    https://numpy.org/doc/stable/reference/generated/numpy.meshgrid.html
    '''
    n=len(a)
    A1=np.repeat(a,n)
    A1=np.reshape(A1,(-1,n))
    A2=A1.copy()
    return A1.T,A2

def new_excluded_pair(C:Any,previously_excluded:List=[],th:float=0.1):
    '''
    Find component pair with highest correlation among pairs that 
    weren't previously excluded.
    Return the i,j of pair if it's correlaiton >= than th.
    Otherwise return None.
    '''
    C_temp = np.triu(np.abs(C),1).copy() # work only on upper triangle, excluding diagonal
    
    if len(previously_excluded)>0:
        C_temp[tuple(zip(*previously_excluded))] = 0
     
    a = np.unravel_index(np.argmax(C_temp), C_temp.shape) 
    cmax = C_temp[a]

    if cmax > th:
        return a
    else:  
        return None

def basis_var(Var_mat,M,V_min:float=1e-4):
    '''
    Estimate the variances of the basis of the compositional data x.
    Assumes that the correlations are sparse (mean correlation is small).
    The element of V_mat are refered to as t_ij in the SparCC paper.
    '''

    V_vec  = Var_mat.sum(axis=1)
    V_base=np.linalg.solve(M,V_vec)
    basis_variance=np.where(V_base <= 0,V_min,V_base)
    return basis_variance


def C_from_V(Var_mat,V_base):
    '''
    Given the estimated basis variances and observed fractions variation matrix, 
    compute the basis correlation & covaraince matrices.
    '''

    Vi, Vj = Mesh(V_base)
    Cov_base = 0.5*(Vi + Vj - Var_mat)
    C_base = Cov_base/np.sqrt(Vi) / np.sqrt(Vj)
    return C_base, Cov_base


def run_sparcc(frame, th:float=0.1,x_iter:int=10):
    '''
    Estimate the correlations of the basis of the compositional data f.
    Assumes that the correlations are sparse (mean correlation is small).
    '''
    ## observed log-ratio variances
    Var_mat = variation_mat(frame)
    Var_mat_temp=Var_mat.copy()
    
    ## Make matrix from eqs. 13 of SparCC paper such that: t_i = M * Basis_Varainces
    D = frame.shape[1] # number of components
    M = np.ones((D,D)) + np.diag([D-2]*D)
 
    ## get approx. basis variances and from them basis covariances/correlations 
    V_base = basis_var(Var_mat_temp, M)
    C_base, Cov_base = C_from_V(Var_mat, V_base)
    
    ## Refine by excluding strongly correlated pairs
    excluded_pairs = []
    excluded_comp  = np.array([])

    for xi in range(x_iter):
        # search for new pair to exclude
        to_exclude = new_excluded_pair(C=C_base,th=th, previously_excluded=excluded_pairs)
    
        if to_exclude is None: #terminate if no new pairs to exclude
            break
        # exclude pair
        excluded_pairs.append(to_exclude)
        i,j = to_exclude
        M[i,j] -= 1
        M[j,i] -= 1
        M[i,i] -= 1
        M[j,j] -= 1
        #inds = zip(*excluded_pairs)
    
        inda,indb=np.transpose(excluded_pairs)
        Var_mat_temp[inda,indb]   = 0
        Var_mat_temp.T[inda,indb] = 0

        # search for new components to exclude
        nexcluded = np.bincount(np.ravel(excluded_pairs)) #number of excluded pairs for each component
        excluded_comp_prev = set(excluded_comp.copy())
        excluded_comp      = np.where(nexcluded>=D-3)[0]
        excluded_comp_new  = set(excluded_comp) - excluded_comp_prev

        if len(excluded_comp_new)>0:
            # check if enough components left 
            if len(excluded_comp) > D-4:
                warnings.warn('Too many component excluded. Returning clr result.')
                return run_clr(frame)
            for xcomp in excluded_comp_new:
                Var_mat_temp[xcomp,:] = 0
                Var_mat_temp[:,xcomp] = 0
                M[xcomp,:] = 0
                M[:,xcomp] = 0
                M[xcomp,xcomp] = 1
        #run another sparcc iteration
        V_base = basis_var(Var_mat_temp, M)
        C_base, Cov_base = C_from_V(Var_mat, V_base)
        
        # set excluded components infered values to nans
        for xcomp in excluded_comp:
            V_base[xcomp] = np.nan
            C_base[xcomp,:] = np.nan
            C_base[:,xcomp] = np.nan
            Cov_base[xcomp,:] = np.nan
            Cov_base[:,xcomp] = np.nan
    return  C_base, Cov_base

def basic_corr(frame, method:str='sparcc',th:float=0.1,x_iter:int=10):
    '''
    Compute the basis correlations between all components of 
    the compositional data f. 
    
    Parameters
    ----------
    frame : array_like
        2D array of relative abundances. 
        Columns are counts, rows are samples. 
    method : str, optional (default 'SparCC')
        The algorithm to use for computing correlation.
        Supported values: SparCC, clr, pearson, spearman, kendall
        Note that the pearson, spearman, kendall methods are not
        altered to account for the fact that the data is compositional,
        and are provided to facilitate comparisons to 
        the clr and sparcc methods.
    th : float,default 0.1 
        Exclusion threshold for SparCC,the valid values are 0.0<th<1.0
    x_iter : int,default 10 
        Number of exclusion iterations for SparCC.

    Returns
    -------
    C_base: array
        Estimated basis correlation matrix.
    Cov_base: array
        Estimated basis covariance matrix.

    ''' 
    #Check th
    assert (th>0 and th<1.0),"The value must be between 0 and 1"

    method = method.lower()

    k = frame.shape[1]
    ## compute basis variances & correlations
    if k<4: 
        logging.info('Can not detect correlations between compositions of <4 components (%d given)' %k)
        raise ValueError('Can not detect correlations between compositions of <4 components (%d given)' %k )    
    if method == 'clr':
        C_base, Cov_base = run_clr(frame)
    elif method == 'sparcc':
        C_base, Cov_base = run_sparcc(frame,th=th,x_iter=x_iter)
        tol = 1e-3 # tolerance for correlation range
        if np.max(np.abs(C_base)) > 1 + tol:
            warnings.warn('Sparcity assumption violated. Returning clr result.')
            C_base, Cov_base = run_clr(frame)    
    else:
        raise ValueError('Unsupported basis correlation method: "%s"' %method)
    return C_base, Cov_base 

def main_alg(frame,method:str='sparcc',
             th:float=0.1,
             x_iter:int=10,
             n_iter:int=20,
             norm:str='dirichlet'):
    '''
    The main function to organize the execution of the algorithm and the 
    processing of temporary files in hdf5 format.

    Parameters
    ----------
    frame : array_like
        2D array of relative abundances. 
        Columns are counts, rows are samples. 
    method : str, optional (default 'SparCC')
        The algorithm to use for computing correlation.
        Supported values: SparCC, clr, pearson, spearman, kendall
        Note that the pearson, spearman, kendall methods are not
        altered to account for the fact that the data is compositional,
        and are provided to facilitate comparisons to 
        the clr and sparcc methods.
    th : float,default 0.1 
        Exclusion threshold for SparCC,the valid values are 0.0<th<1.0
    x_iter : int,default 10 
        Number of exclusion iterations for SparCC.
    n_iter : int,default 20
        Number of estimation iteration to average over.
    norm : str,(dirichlet|norm),defualt: dirichlet
        Method used to normalize the counts to fractions.

    Returns
    -------
    C_base: array
        Estimated basis correlation matrix.
    Cov_base: array
        Estimated basis covariance matrix.

    '''
    fracs = to_fractions(frame, method=norm)
    cor_sparse, cov_sparse = basic_corr(fracs, method=method,th=th,x_iter=x_iter)
    var_cov=np.diag(cov_sparse)
        
    var_med=np.nanmedian(cov_sparse,axis=0)
    cor_med=np.nanmedian(cor_sparse,axis=0)

    x,y=Mesh(var_med)
    cov_med=cor_med*x**0.5*y**0.5
    logging.info("The main process has finished")

    return cor_med,cov_med

