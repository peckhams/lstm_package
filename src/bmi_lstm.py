# Need these for BMI
from bmipy import Bmi
import time
#import data_tools
# Basic utilities
import numpy as np
import pandas as pd
import pickle
from pathlib import Path
# Here is the LSTM model we want to run
import nextgen_cuda_lstm
# Configuration file functionality
import yaml
# LSTM here is based on PyTorch
import torch
from torch import nn
import sys

class bmi_LSTM(Bmi):

    def __init__(self):
        """Create a Bmi LSTM model that is ready for initialization."""
        super(bmi_LSTM, self).__init__()
        self._name = "LSTM for Next Generation NWM"
        self._values = {}
        self._var_loc = "node"
        self._var_grid_id = 0
        self._var_grid_type = "scalar"
        self._start_time = 0
        self._end_time = np.finfo("d").max
        self._time_units = "hour"
        self._time_step_size = 1
        
        # Note: these need to be initialized here as scale_output() called in update()
        self.streamflow_cms = 0.0
        self.streamflow_fms = 0.0
        self.surface_runoff_mm = 0.0

    #----------------------------------------------
    # Required, static attributes of the model
    #----------------------------------------------
    # Note: not currently in use
    _att_map = {
        'model_name':         'LSTM for Next Generation NWM',
        'version':            '1.0',
        'author_name':        'Jonathan Martin Frame' }

    #---------------------------------------------
    # Input variable names (CSDMS standard names)
    #---------------------------------------------
    _input_var_names = [
        'land_surface_radiation~incoming~longwave__energy_flux',
        'land_surface_air__pressure',
        'atmosphere_air_water~vapor__relative_saturation',
        'atmosphere_water__time_integral_of_precipitation_mass_flux',
        'land_surface_radiation~incoming~shortwave__energy_flux',
        'land_surface_air__temperature',
        'land_surface_wind__x_component_of_velocity',
        'land_surface_wind__y_component_of_velocity']

    #---------------------------------------------
    # Output variable names (CSDMS standard names)
    #---------------------------------------------
    _output_var_names = ['land_surface_water__runoff_depth', 
                         'land_surface_water__runoff_volume_flux']

    #------------------------------------------------------
    # Create a Python dictionary that maps CSDMS Standard
    # Names to the model's internal variable names.
    # This is going to get long, 
    #     since the input variable names could come from any forcing...
    #------------------------------------------------------
    #_var_name_map_long_first = {
    _var_name_units_map = {
                                'land_surface_water__runoff_volume_flux':['streamflow_cms','m3 s-1'],
                                'land_surface_water__runoff_depth':['streamflow_m','m'],
                                #--------------   Dynamic inputs --------------------------------
                                #NJF Let the model assume equivalence of `kg m-2` == `mm h-1` since we can't convert
                                #mass flux automatically from the ngen framework
                                #'atmosphere_water__time_integral_of_precipitation_mass_flux':['total_precipitation','kg m-2'],
                                'atmosphere_water__time_integral_of_precipitation_mass_flux':['total_precipitation','mm h-1'],
                                'land_surface_radiation~incoming~longwave__energy_flux':['longwave_radiation','W m-2'],
                                'land_surface_radiation~incoming~shortwave__energy_flux':['shortwave_radiation','W m-2'],
                                'atmosphere_air_water~vapor__relative_saturation':['specific_humidity','kg kg-1'],
                                'land_surface_air__pressure':['pressure','Pa'],
                                'land_surface_air__temperature':['temperature','degC'],
                                'land_surface_wind__x_component_of_velocity':['wind_u','m s-1'],
                                'land_surface_wind__y_component_of_velocity':['wind_v','m s-1'],
                                #--------------   STATIC Attributes -----------------------------
                                'basin__area':['area_gages2','km2'],
                                'ratio__mean_potential_evapotranspiration__mean_precipitation':['aridity','-'],
                                'basin__carbonate_rocks_area_fraction':['carbonate_rocks_frac','-'],
                                'soil_clay__volume_fraction':['clay_frac','percent'],
                                'basin__mean_of_elevation':['elev_mean','m'],
                                'land_vegetation__forest_area_fraction':['frac_forest','-'],
                                'atmosphere_water__precipitation_falling_as_snow_fraction':['frac_snow','-'],
                                'bedrock__permeability':['geol_permeability','m2'],
                                'land_vegetation__max_monthly_mean_of_green_vegetation_fraction':['gvf_max','-'],
                                'land_vegetation__diff__max_min_monthly_mean_of_green_vegetation_fraction':['gvf_diff','-'],
                                'atmosphere_water__mean_duration_of_high_precipitation_events':['high_prec_dur','d'],
                                'atmosphere_water__frequency_of_high_precipitation_events':['high_prec_freq','d yr-1'],
                                'land_vegetation__diff_max_min_monthly_mean_of_leaf-area_index':['lai_diff','-'],
                                'land_vegetation__max_monthly_mean_of_leaf-area_index':['lai_max','-'],
                                'atmosphere_water__low_precipitation_duration':['low_prec_dur','d'],
                                'atmosphere_water__precipitation_frequency':['low_prec_freq','d yr-1'],
                                'maximum_water_content':['max_water_content','m'],
                                'atmosphere_water__daily_mean_of_liquid_equivalent_precipitation_rate':['p_mean','mm d-1'],
                                'land_surface_water__daily_mean_of_potential_evaporation_flux':['pet_mean','mm d-1'],
                                'basin__mean_of_slope':['slope_mean','m km-1'],
                                'soil__saturated_hydraulic_conductivity':['soil_conductivity','cm hr-1'],
                                'soil_bedrock_top__depth__pelletier':['soil_depth_pelletier','m'],
                                'soil_bedrock_top__depth__statsgo':['soil_depth_statsgo','m'],
                                'soil__porosity':['soil_porosity','-'],
                                'soil_sand__volume_fraction':['sand_frac','percent'],
                                'soil_silt__volume_fraction':['silt_frac','percent'], 
                                'basin_centroid__latitude':['gauge_lat', 'degrees'],
                                'basin_centroid__longitude':['gauge_lon', 'degrees']
                                 }

    #------------------------------------------------------
    # A list of static attributes. Not all these need to be used.
    #------------------------------------------------------
    #   These attributes can be anaything, but usually come from the CAMELS attributes:
    #   Nans Addor Andrew J. Newman, Naoki Mizukami, and Martyn P. Clark
    #   The CAMELS data set: catchment attributes and meteorology for large-sample studies
    #   https://doi.org/10.5194/hess-21-5293-2017
    _static_attributes_list = ['area_gages2','aridity','carbonate_rocks_frac','clay_frac',
                               'elev_mean','frac_forest','frac_snow','geol_permeability',
                               'gvf_max','gvf_diff','high_prec_dur','high_prec_freq','lai_diff',
                               'lai_max','low_prec_dur','low_prec_freq','max_water_content',
                               'p_mean','pet_mean','slope_mean','soil_conductivity',
                               'soil_depth_pelletier','soil_depth_statsgo','soil_porosity',
                               'sand_frac','silt_frac', 'gauge_lat', 'gauge_lon']

    def __getattribute__(self, item):
        """
        Customize instance attribute access.

        For those items that correspond to BMI input or output variables (which should be in numpy arrays) and have
        values that are just a single-element array, deviate from the standard behavior and return the single array
        element.  Fall back to the default behavior in any other case.

        This supports having a BMI variable be backed by a numpy array, while also allowing the attribute to be used as
        just a scalar, as it is in many places for this type.

        Parameters
        ----------
        item
            The name of the attribute item to get.

        Returns
        -------
        The value of the named item.
        """
        # Have these work explicitly (or else loops)
        if item == '_input_var_names' or item == '_output_var_names':
            return super(bmi_LSTM, self).__getattribute__(item)

        # By default, for things other than BMI variables, use normal behavior
        if item not in super(bmi_LSTM, self).__getattribute__('_input_var_names') and item not in super(bmi_LSTM, self).__getattribute__('_output_var_names'):
            return super(bmi_LSTM, self).__getattribute__(item)

        # Return the single scalar value from any ndarray of size 1
        value = super(bmi_LSTM, self).__getattribute__(item)
        if isinstance(value, np.ndarray) and value.size == 1:
            return value[0]
        else:
            return value

    def __setattr__(self, key, value):
        """
        Customized instance attribute mutator functionality.

        For those attribute with keys indicating they are a BMI input or output variable (which should be in numpy
        arrays), wrap any scalar ``value`` as a one-element numpy array and use that in a nested call to the superclass
        implementation of this function.  In any other cases, just pass the given ``key`` and ``value`` to a nested
        call.

        This supports automatically having a BMI variable be backed by a numpy array, even if it is initialized using a
        scalar, while otherwise maintaining standard behavior.

        Parameters
        ----------
        key
        value

        Returns
        -------

        """
        # Have these work explicitly (or else loops)
        if key == '_input_var_names' or key == '_output_var_names':
            super(bmi_LSTM, self).__setattr__(key, value)

        # Pass thru if value is already an array
        if isinstance(value, np.ndarray):
            super(bmi_LSTM, self).__setattr__(key, value)
        # Override to put scalars into ndarray for BMI input/output variables
        elif key in self._input_var_names or key in self._output_var_names:
            super(bmi_LSTM, self).__setattr__(key, np.array([value]))
        # By default, use normal behavior
        else:
            super(bmi_LSTM, self).__setattr__(key, value)

    #------------------------------------------------------------
    #------------------------------------------------------------
    # BMI: Model Control Functions
    #------------------------------------------------------------ 
    #------------------------------------------------------------

    #-------------------------------------------------------------------
    def initialize( self, bmi_cfg_file=None ):
        #NJF ensure this is a Path type so the follow open works as expected
        #When used with NGen, the bmi_cfg_file is just a string...
        bmi_cfg_file = Path(bmi_cfg_file)
        # ----- Create some lookup tabels from the long variable names --------#
        self._var_name_map_long_first = {long_name:self._var_name_units_map[long_name][0] for \
                                         long_name in self._var_name_units_map.keys()}
        self._var_name_map_short_first = {self._var_name_units_map[long_name][0]:long_name for \
                                          long_name in self._var_name_units_map.keys()}
        self._var_units_map = {long_name:self._var_name_units_map[long_name][1] for \
                                          long_name in self._var_name_units_map.keys()}
        
        # -------------- Initalize all the variables --------------------------# 
        # -------------- so that they'll be picked up with the get functions --#
        for var_name in list(self._var_name_units_map.keys()):
            # ---------- All the variables are single values ------------------#
            # ---------- so just set to zero for now.        ------------------#
            #self._values[var_name] = 0
            setattr( self, var_name, 0 )
        
        # -------------- Read in the BMI configuration -------------------------#
        # This will direct all the next moves.
        if bmi_cfg_file is not None:

            with bmi_cfg_file.open('r') as fp:
                cfg = yaml.safe_load(fp)
            self.cfg_bmi = self._parse_config(cfg)
        else:
            print("Error: No configuration provided, nothing to do...")
        
        # ------------- Load in the configuration file for the specific LSTM --#
        # This will include all the details about how the model was trained
        # Inputs, outputs, hyper-parameters, scalers, weights, etc. etc.
        self.get_training_configurations()
        self.get_scaler_values()
        
        # ------------- Initialize an LSTM model ------------------------------#
        self.lstm = nextgen_cuda_lstm.Nextgen_CudaLSTM(input_size=self.input_size, 
                                                       hidden_layer_size=self.hidden_layer_size, 
                                                       output_size=self.output_size, 
                                                       batch_size=1, 
                                                       seq_length=1)

        # ------------ Load in the trained weights ----------------------------#
        # Save the default model weights. We need to make sure we have the same keys.
        default_state_dict = self.lstm.state_dict()

        # Trained model weights from Neuralhydrology.
        trained_model_file = '..' / self.cfg_train['run_dir'] / 'model_epoch{}.pt'.format(str(self.cfg_train['epochs']).zfill(3))
        trained_state_dict = torch.load(trained_model_file, map_location=torch.device('cpu'))

        # Changing the name of the head weights, since different in NH
        trained_state_dict['head.weight'] = trained_state_dict.pop('head.net.0.weight')
        trained_state_dict['head.bias'] = trained_state_dict.pop('head.net.0.bias')
        trained_state_dict = {x:trained_state_dict[x] for x in default_state_dict.keys()}

        # Load in the trained weights.
        self.lstm.load_state_dict(trained_state_dict)

        # ------------- Initialize the values for the input to the LSTM  -----#
        self.set_static_attributes()
        self.initialize_forcings()
        
        if self.cfg_bmi['initial_state'] == 'zero':
            self.h_t = torch.zeros(1, self.batch_size, self.hidden_layer_size).float()
            self.c_t = torch.zeros(1, self.batch_size, self.hidden_layer_size).float()

        # ------------- Start a simulation time  -----------------------------#
        # jmframe: Since the simulation time here doesn't really matter. 
        #          Just use seconds and set the time to zero
        #          But add some logic maybe, so to be able to start at some time
        self.t = self._start_time

        # ----------- The output is area normalized, this is needed to un-normalize it
        #                         mm->m                             km2 -> m2          hour->s    
        self.output_factor_cms =  (1/1000) * (self.cfg_bmi['area_sqkm'] * 1000*1000) * (1/3600)

        # Gather verbosity lvl from bmi-config for stdout printing, etc.    
        self.verbose = self.cfg_bmi['verbose']

    #------------------------------------------------------------ 
    def update(self):
        with torch.no_grad():

            self.create_scaled_input_tensor()

            self.lstm_output, self.h_t, self.c_t = self.lstm.forward(self.input_tensor, self.h_t, self.c_t)
            
            self.scale_output()
            
            #self.t += self._time_step_size
            self.t += self.get_time_step()

    #------------------------------------------------------------ 
    def update_frac(self, time_frac):
        """Update model by a fraction of a time step.
        Parameters
        ----------
        time_frac : float
            Fraction fo a time step.
        """
        if self.verbose > 0:
            print("Warning: This version of the LSTM is designed to make predictions on one hour timesteps.")
        time_step = self.get_time_step()
        self._time_step_size = time_frac * self._time_step_size
        self.update()
        self._time_step_size = time_step

    #------------------------------------------------------------ 
    def update_until(self, then):
        """Update model until a particular time.
        Parameters
        ----------
        then : float
            Time to run model until.
        """
        if self.verbose > 0:
            print("then", then)
            print("self.get_current_time()", self.get_current_time())
            print("self.get_time_step()", self.get_time_step())
        n_steps = (then - self.get_current_time()) / self.get_time_step()

        for _ in range(int(n_steps)):
            self.update()
        self.update_frac(n_steps - int(n_steps))

    #------------------------------------------------------------ 
    # def update_until(self, last_update):
    #    first_update=self.t
    #    for t in range(first_update, last_update):
    #        self.update()
    #------------------------------------------------------------    
    def finalize( self ):
        """Finalize model."""
        self._model = None
    
    #------------------------------------------------------------
    #------------------------------------------------------------
    # LSTM: SETUP Functions
    #------------------------------------------------------------
    #------------------------------------------------------------

    #-------------------------------------------------------------------
    def get_training_configurations(self):
        if self.cfg_bmi['train_cfg_file'] is not None:
            with self.cfg_bmi['train_cfg_file'].open('r') as fp:
                cfg = yaml.safe_load(fp)
            self.cfg_train = self._parse_config(cfg)

        # Collect the LSTM model architecture details from the configuration file
        self.input_size        = len(self.cfg_train['dynamic_inputs']) + len(self.cfg_train['static_attributes'])
        self.hidden_layer_size = self.cfg_train['hidden_size']
        self.output_size       = len(self.cfg_train['target_variables']) 

        # WARNING: This implimentation of the LSTM can only handle a batch size of 1
        self.batch_size        = 1 #self.cfg_train['batch_size']

        # Including a list of the model input names.
        self.all_lstm_inputs = []
        self.all_lstm_inputs.extend(self.cfg_train['dynamic_inputs'])
        self.all_lstm_inputs.extend(self.cfg_train['static_attributes'])
        
        # Scaler data from the training set. This is used to normalize the data (input and output).
        with open('..' / self.cfg_train['run_dir'] / 'train_data' / 'train_data_scaler.p', 'rb') as fb:
            self.train_data_scaler = pickle.load(fb)

    #------------------------------------------------------------ 
    def get_scaler_values(self):

        """Mean and standard deviation for the inputs and LSTM outputs""" 

        self.out_mean = self.train_data_scaler['xarray_feature_center'][self.cfg_train['target_variables'][0]].values
        self.out_std = self.train_data_scaler['xarray_feature_scale'][self.cfg_train['target_variables'][0]].values

        self.input_mean = []
        self.input_mean.extend([self.train_data_scaler['xarray_feature_center'][x].values for x in self.cfg_train['dynamic_inputs']])
        self.input_mean.extend([self.train_data_scaler['attribute_means'][x] for x in self.cfg_train['static_attributes']])
        self.input_mean = np.array(self.input_mean)

        self.input_std = []
        self.input_std.extend([self.train_data_scaler['xarray_feature_scale'][x].values for x in self.cfg_train['dynamic_inputs']])
        self.input_std.extend([self.train_data_scaler['attribute_stds'][x] for x in self.cfg_train['static_attributes']]) 
        self.input_std = np.array(self.input_std)

    #------------------------------------------------------------ 
    def create_scaled_input_tensor(self):
        
        # TODO: Choose to store values in dictionary or not.
        self.input_array = np.array([getattr(self, self._var_name_map_short_first[x]) for x in self.all_lstm_inputs])
        #self.input_array = np.array([self._values[self._var_name_map_short_first[x]] for x in self.all_lstm_inputs])
        
        self.input_array_scaled = (self.input_array - self.input_mean) / self.input_std 
        self.input_tensor = torch.tensor(self.input_array_scaled)
        
    #------------------------------------------------------------ 
    def scale_output(self):

        if self.cfg_train['target_variables'][0] == 'qobs_mm_per_hour':
            self.surface_runoff_mm = (self.lstm_output[0,0,0].numpy().tolist() * self.out_std + self.out_mean)

        elif self.cfg_train['target_variables'][0] == 'QObs(mm/d)':
            self.surface_runoff_mm = (self.lstm_output[0,0,0].numpy().tolist() * self.out_std + self.out_mean) * (1/24)
            
        # Bound the runoff to zero or obs, as negative values are illogical
        #if self.surface_runoff_mm < 0.0: self.surface_runoff_mm = 0.0
        #np.maximum( self.surface_runoff_mm, 0.0, self.surface_runoff_mm)
        self.surface_runoff_mm = max(self.surface_runoff_mm,0.0)

        #self._values['land_surface_water__runoff_depth'] = self.surface_runoff_mm/1000.0
        setattr(self, 'land_surface_water__runoff_depth', self.surface_runoff_mm/1000.0)
        self.streamflow_cms = self.surface_runoff_mm * self.output_factor_cms

        #self._values['land_surface_water__runoff_volume_flux'] = self.streamflow_cms
        setattr(self, 'land_surface_water__runoff_volume_flux', self.streamflow_cms)

    #-------------------------------------------------------------------
    def read_initial_states(self):
        h_t = np.genfromtxt(self.h_t_init_file, skip_header=1, delimiter=",")[:,1]
        self.h_t = torch.tensor(h_t).view(1,1,-1)
        c_t = np.genfromtxt(self.c_t_init_file, skip_header=1, delimiter=",")[:,1]
        self.c_t = torch.tensor(c_t).view(1,1,-1)

    #---------------------------------------------------------------------------- 
    def set_static_attributes(self):
        """ Get the static attributes from the configuration file
        """
        for attribute in self._static_attributes_list:
            if attribute in self.cfg_train['static_attributes']:
                
                long_var_name = self._var_name_map_short_first[attribute]

                # This is probably the better way to do it,
                setattr(self, long_var_name, self.cfg_bmi[attribute])
                
                # and this is just in case. _values dictionary is in the example
                #self._values[long_var_name] = self.cfg_bmi[attribute]
    
    #---------------------------------------------------------------------------- 
    def initialize_forcings(self):
        for forcing_name in self.cfg_train['dynamic_inputs']:
            setattr(self, self._var_name_map_short_first[forcing_name], 0)

    #-------------------------------------------------------------------
    #-------------------------------------------------------------------
    # BMI: Model Information Functions
    #-------------------------------------------------------------------
    #-------------------------------------------------------------------
    
    # Note: not currently using _att_map{}
    # def get_attribute(self, att_name):
    
    #     try:
    #         return self._att_map[ att_name.lower() ]
    #     except:
    #         print(' ERROR: Could not find attribute: ' + att_name)

    #--------------------------------------------------------
    # Note: These are currently variables needed from other
    #       components vs. those read from files or GUI.
    #--------------------------------------------------------   
    def get_input_var_names(self):

        return self._input_var_names

    def get_output_var_names(self):
 
        return self._output_var_names

    #------------------------------------------------------------ 
    def get_component_name(self):
        """Name of the component."""
        #return self.get_attribute( 'model_name' )
        return self._name

    #------------------------------------------------------------ 
    def get_input_item_count(self):
        """Get names of input variables."""
        return len(self._input_var_names)

    #------------------------------------------------------------ 
    def get_output_item_count(self):
        """Get names of output variables."""
        return len(self._output_var_names)

    #------------------------------------------------------------ 
    def get_value(self, var_name: str, dest: np.ndarray) -> np.ndarray:
        """
        Copy values for the named variable into the provided destination array.

        Parameters
        ----------
        var_name : str
            Name of variable as CSDMS Standard Name.
        dest : np.ndarray
            A numpy array into which to copy the variable values.
        Returns
        -------
        np.ndarray
            Copy of values.
        """
        dest[:] = self.get_value_ptr(var_name)
        return dest

    #-------------------------------------------------------------------
    def get_value_ptr(self, var_name: str) -> np.ndarray:
        """
        Get reference to values.

        Get the backing reference - i.e., the backing numpy array - for the given variable.

        Parameters
        ----------
        var_name : str
            Name of variable as CSDMS Standard Name.
        Returns
        -------
        np.ndarray
            Value array.
        """
        # if getattr(self, var_name) != self._values[var_name]:
        #     if self.verbose > 0:
        #         print("WARNING: The variable ({}) stored in two locations is inconsistent".format(var_name))
        #         print('getattr(self, var_name)', getattr(self, var_name))
        #         print('self.surface_runoff_mm', self.surface_runoff_mm)
        #         print('self._values[var_name]', self._values[var_name])

        # We actually need this function to return the backing array, so bypass override of __getattribute__ (that
        # extracts scalar) and use the base implementation
        return super(bmi_LSTM, self).__getattribute__(var_name)

    #-------------------------------------------------------------------
    #-------------------------------------------------------------------
    # BMI: Variable Information Functions
    #-------------------------------------------------------------------
    #-------------------------------------------------------------------
    def get_var_name(self, long_var_name):
                              
        return self._var_name_map_long_first[ long_var_name ]

    #-------------------------------------------------------------------
    def get_var_units(self, long_var_name):

        return self._var_units_map[ long_var_name ]
                                                             
    #-------------------------------------------------------------------
    def get_var_type(self, long_var_name):
        """Data type of variable.

        Parameters
        ----------
        var_name : str
            Name of variable as CSDMS Standard Name.

        Returns
        -------
        str
            Data type.
        """
        #NJF Need an actual type here...
        return type(self.get_value_ptr(long_var_name)).__name__ #.dtype
    #------------------------------------------------------------ 
    def get_var_grid(self, name):
        
        # Note: all vars have grid 0 but check if its in names list first
        if name in (self._output_var_names + self._input_var_names):
            return self._var_grid_id  

    #------------------------------------------------------------ 
    def get_var_itemsize(self, name):
#        return np.dtype(self.get_var_type(name)).itemsize
        return self.get_value_ptr(name).itemsize

    #------------------------------------------------------------ 
    def get_var_location(self, name):
        
        # Note: all vars have location node but check if its in names list first
        if name in (self._output_var_names + self._input_var_names):
            return self._var_loc

    #-------------------------------------------------------------------
    # JG Note: what is this used for?
    def get_var_rank(self, long_var_name):

        return np.int16(0)

    #-------------------------------------------------------------------
    def get_start_time( self ):
    
        return self._start_time

    #-------------------------------------------------------------------
    def get_end_time( self ):

        return self._end_time


    #-------------------------------------------------------------------
    def get_current_time( self ):

        return self.t

    #-------------------------------------------------------------------
    def get_time_step( self ):

        #return self.get_attribute( 'time_step_size' )
        return self._time_step_size

    #-------------------------------------------------------------------
    def get_time_units( self ):

        #return self.get_attribute( 'time_units' )
        return self._time_units
       
    #-------------------------------------------------------------------
    def set_value(self, var_name: str, values: np.ndarray):
        """Set model values.

        Parameters
        ----------
        var_name : str
            Name of variable as CSDMS Standard Name.
        values : np.ndarray
              Array of new values.
        """
        internal_array = self.get_value_ptr(var_name)
        #self.get_value_ptr(var_name)[:] = values
        internal_array[:] = values

    #------------------------------------------------------------ 
    def set_value_at_indices(self, var_name: str, inds: np.ndarray, src: np.ndarray):
        """
        Set model values at particular indices.

        Parameters
        ----------
        var_name : str
            Name of variable as CSDMS Standard Name.
        inds : np.ndarray
            Array of corresponding indices into which to copy the values within ``src``.
        src : np.ndarray
            Array of new values.
        """
        internal_array = self.get_value_ptr(var_name)
        for i in range(inds.shape[0]):
            internal_array[inds[i]] = src[i]

    #------------------------------------------------------------ 
    def get_var_nbytes(self, var_name):
        """Get units of variable.
        Parameters
        ----------
        var_name : str
            Name of variable as CSDMS Standard Name.
        Returns
        -------
        int
            Size of data array in bytes.
        """
        # JMFrame NOTE: Had to import sys for this function
        #NJF getsizeof returns the size of the python object...not the raw dtype...
        #return sys.getsizeof(self.get_value_ptr(var_name))
        #This is just the itemsize (size per element) * number of elements
        #Since all are currently scalar, this is 1
        try:
            return self.get_var_itemsize(var_name)*len(self.get_value_ptr(var_name))
        except TypeError:
            #must be scalar
            return self.get_var_itemsize(var_name)
    #------------------------------------------------------------ 
    def get_value_at_indices(self, var_name: str, dest: np.ndarray, indices: np.ndarray) -> np.ndarray:
        """
        Get values at particular indices.

        Parameters
        ----------
        var_name : str
            Name of variable as CSDMS Standard Name.
        dest : np.ndarray
            A numpy array into which to place the values.
        indices : array_like
            Array of indices.
        Returns
        -------
        np.ndarray
            Values at indices.
        """
        original: np.ndarray = self.get_value_ptr(var_name)
        for i in range(indices.shape[0]):
            value_index = indices[i]
            dest[i] = original[value_index]
        return dest
 
    #   Note: remaining grid funcs do not apply for type 'scalar'
    #   Yet all functions in the BMI must be implemented 
    #   See https://bmi.readthedocs.io/en/latest/bmi.best_practices.html          
    #------------------------------------------------------------ 
    def get_grid_edge_count(self, grid):
        raise NotImplementedError("get_grid_edge_count")

    #------------------------------------------------------------ 
    def get_grid_edge_nodes(self, grid, edge_nodes):
        raise NotImplementedError("get_grid_edge_nodes")

    #------------------------------------------------------------ 
    def get_grid_face_count(self, grid):
        raise NotImplementedError("get_grid_face_count")
    
    #------------------------------------------------------------ 
    def get_grid_face_edges(self, grid, face_edges):
        raise NotImplementedError("get_grid_face_edges")

    #------------------------------------------------------------ 
    def get_grid_face_nodes(self, grid, face_nodes):
        raise NotImplementedError("get_grid_face_nodes")
    
    #------------------------------------------------------------ 
    def get_grid_node_count(self, grid):
        raise NotImplementedError("get_grid_node_count")

    #------------------------------------------------------------ 
    def get_grid_nodes_per_face(self, grid, nodes_per_face):
        raise NotImplementedError("get_grid_nodes_per_face") 
    
    #------------------------------------------------------------ 
    def get_grid_origin(self, grid_id, origin):
        raise NotImplementedError("get_grid_origin") 

    #------------------------------------------------------------ 
    def get_grid_rank(self, grid_id):
 
         # 0 is the only id we have
        if grid_id == 0: 
            return 1

    #------------------------------------------------------------ 
    def get_grid_shape(self, grid_id, shape):
        raise NotImplementedError("get_grid_shape") 

    #------------------------------------------------------------ 
    def get_grid_size(self, grid_id):
       
        # 0 is the only id we have
        if grid_id == 0:
            return 1

    #------------------------------------------------------------ 
    def get_grid_spacing(self, grid_id, spacing):
        raise NotImplementedError("get_grid_spacing") 

    #------------------------------------------------------------ 
    def get_grid_type(self, grid_id=0):

        # 0 is the only id we have        
        if grid_id == 0:
            return 'scalar'

    #------------------------------------------------------------ 
    def get_grid_x(self):
        raise NotImplementedError("get_grid_x") 

    #------------------------------------------------------------ 
    def get_grid_y(self):
        raise NotImplementedError("get_grid_y") 

    #------------------------------------------------------------ 
    def get_grid_z(self):
        raise NotImplementedError("get_grid_z") 


    #------------------------------------------------------------ 
    #------------------------------------------------------------ 
    #-- Random utility functions
    #------------------------------------------------------------ 
    #------------------------------------------------------------ 

    def _parse_config(self, cfg):
        for key, val in cfg.items():
            # convert all path strings to PosixPath objects
            if any([key.endswith(x) for x in ['_dir', '_path', '_file', '_files']]):
                if (val is not None) and (val != "None"):
                    if isinstance(val, list):
                        temp_list = []
                        for element in val:
                            temp_list.append(Path(element))
                        cfg[key] = temp_list
                    else:
                        cfg[key] = Path(val)
                else:
                    cfg[key] = None

            # convert Dates to pandas Datetime indexs
            elif key.endswith('_date'):
                if isinstance(val, list):
                    temp_list = []
                    for elem in val:
                        temp_list.append(pd.to_datetime(elem, format='%d/%m/%Y'))
                    cfg[key] = temp_list
                else:
                    cfg[key] = pd.to_datetime(val, format='%d/%m/%Y')

            else:
                pass

        # Add more config parsing if necessary
        return cfg
