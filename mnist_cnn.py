# Copyright 2015 Matthieu Courbariaux

# This file is part of BinaryConnect.

# BinaryConnect is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

# BinaryConnect is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with BinaryConnect.  If not, see <http://www.gnu.org/licenses/>.

import gzip
import cPickle
import numpy as np
import os
import os.path
import sys
import time

from trainer import Trainer
from model import Network
from layer import linear_layer, ReLU_layer, ReLU_conv_layer  

from pylearn2.datasets.mnist import MNIST
from pylearn2.utils import serial
          
def onehot(x,numclasses=None):

    if x.shape==():
        x = x[None]
    if numclasses is None:
        numclasses = np.max(x) + 1
    result = np.zeros(list(x.shape) + [numclasses], dtype="int")
    z = np.zeros(x.shape, dtype="int")
    for c in range(numclasses):
        z *= 0
        z[np.where(x==c)] = 1
        result[...,c] += z

    result = np.reshape(result,(np.shape(result)[0], np.shape(result)[result.ndim-1]))
    return result
       
# MAIN

if __name__ == "__main__":
    
    print 'Hyperparameters' 
    
    rng = np.random.RandomState(1234)
    # rng = np.random.RandomState(int(sys.argv[1]))
    train_set_size = 50000
    # train_set_size = 100 # for testing data augmentation
    
    # data augmentation
    zero_pad = 0
    affine_transform_a = 0
    affine_transform_b = 0
    horizontal_flip = False
    
    # batch
    # keep a multiple a factor of 10000 if possible
    # 10000 = (2*5)^4
    batch_size = 100
    number_of_batches_on_gpu = train_set_size/batch_size
    BN = True
    BN_epsilon=1e-4 # for numerical stability
    BN_fast_eval= True
    dropout_input = .9
    # dropout_input = float(sys.argv[2])
    dropout_hidden = .75
    # dropout_hidden = float(sys.argv[3])
    shuffle_examples = True
    shuffle_batches = False

    # Termination criteria
    n_epoch = 100
    # n_epoch = int(sys.argv[4])
    monitor_step = 2
    # core_path = "cnn_exp/" + str(sys.argv)
    load_path = None    
    # load_path = core_path + ".pkl"
    save_path = None
    # save_path = core_path + ".pkl"
    # print save_path
    
    # LR 
    LR = .03
    # LR = float(sys.argv[5])
    LR_fin = .03
    # LR_fin = float(sys.argv[6])
    # LR_decay = 1. 
    LR_decay = (LR_fin/LR)**(1./n_epoch)    
    M= 0.
    
    # architecture
    # greatly inspired from http://arxiv.org/pdf/1412.6071v4.pdf
    ReLU_slope = 0.
    channel_size = 30
    n_channels = 16# number of channels of the first layer
    n_classes = 10
    length = 3 # number of C2-C2-MP2
    n_hidden_layer = (length+1)*2
    
    # BinaryConnect
    BinaryConnect = False
    # BinaryConnect = int(sys.argv[8])
    stochastic = False
    # stochastic = int(sys.argv[9])
    
    # Old hyperparameters
    binary_training=False 
    stochastic_training=False
    binary_test=False
    stochastic_test=False
    if BinaryConnect == True:
        binary_training=True      
        if stochastic == True:   
            stochastic_training=True  
        else:
            binary_test=True
    
    print 'Loading the dataset' 
    
    train_set = MNIST(which_set= 'train', start=0, stop = train_set_size, center = True)
    valid_set = MNIST(which_set= 'train', start=50000, stop = 60000, center = True)
    test_set = MNIST(which_set= 'test', center = True)
    
    # bc01 format
    train_set.X = train_set.X.reshape(train_set_size,1,28,28)
    valid_set.X = valid_set.X.reshape(10000,1,28,28)
    test_set.X = test_set.X.reshape(10000,1,28,28)
    
    # Onehot the targets
    train_set.y = np.float32(onehot(train_set.y))
    valid_set.y = np.float32(onehot(valid_set.y))
    test_set.y = np.float32(onehot(test_set.y))
    
    # for hinge loss
    train_set.y = 2* train_set.y - 1.
    valid_set.y = 2* valid_set.y - 1.
    test_set.y = 2* test_set.y - 1.
    
    # print train_set.X
    # print np.shape(train_set.X)
    # print np.max(train_set.X)
    # print np.min(train_set.X)
    
    print 'Creating the model'
    
    class DeepCNN(Network):

        def __init__(self, rng):

            Network.__init__(self, n_hidden_layer = n_hidden_layer, BN = BN)
            
            local_channel_size = channel_size
            
            for i in range(length):
                
                print "    C2 layer:"
                
                self.layer.append(ReLU_conv_layer(
                    rng,
                    image_shape=(batch_size, n_channels * i + (i==0), local_channel_size, local_channel_size),
                    filter_shape=(n_channels*(i+1), n_channels * i + (i==0), 2, 2),
                    pool_shape=(1,1),
                    ReLU_slope = ReLU_slope,
                    BN = BN,                     
                    BN_epsilon=BN_epsilon,
                    binary_training=binary_training, 
                    stochastic_training=stochastic_training,
                    binary_test=binary_test, 
                    stochastic_test=stochastic_test
                ))
                
                # valid C2
                local_channel_size = local_channel_size-1
                
                print "    C2 + MP2 layer:"
                
                self.layer.append(ReLU_conv_layer(
                    rng,
                    image_shape=(batch_size, n_channels*(i+1), local_channel_size, local_channel_size),
                    filter_shape=(n_channels*(i+1), n_channels*(i+1), 2, 2),
                    pool_shape=(2, 2),
                    ReLU_slope = ReLU_slope,
                    BN = BN,
                    BN_epsilon=BN_epsilon,
                    binary_training=binary_training, 
                    stochastic_training=stochastic_training,
                    binary_test=binary_test, 
                    stochastic_test=stochastic_test
                ))
                
                # valid C2 and MP2
                local_channel_size = (local_channel_size-1)/2
            
            print "    C2 layer:"
            
            self.layer.append(ReLU_conv_layer(
                rng,
                image_shape=(batch_size, n_channels*length, local_channel_size, local_channel_size),
                filter_shape=(n_channels*(length+1), n_channels*length, 2, 2),
                pool_shape=(1,1),
                ReLU_slope = ReLU_slope,
                BN = BN,
                BN_epsilon=BN_epsilon,
                binary_training=binary_training, 
                stochastic_training=stochastic_training,
                binary_test=binary_test, 
                stochastic_test=stochastic_test
            ))
            
            # valid C2
            local_channel_size = local_channel_size-1
            
            # print "    C1 layer:"
            
            self.layer.append(ReLU_conv_layer(
                rng,
                image_shape=(batch_size, n_channels*(length+1), local_channel_size, local_channel_size),
                filter_shape=(n_channels*(length+2), n_channels*(length+1), 1, 1),
                pool_shape=(1,1),
                ReLU_slope = ReLU_slope,
                BN = BN,
                BN_epsilon=BN_epsilon,
                binary_training=binary_training, 
                stochastic_training=stochastic_training,
                binary_test=binary_test, 
                stochastic_test=stochastic_test
            ))
            
            print "    L2 SVM layer:"
            
            self.layer.append(linear_layer(
                rng = rng, 
                n_inputs= n_channels*(length+2)*local_channel_size*local_channel_size, 
                n_units = n_classes, 
                BN = BN,
                BN_epsilon=BN_epsilon,
                dropout = dropout_hidden,
                binary_training=binary_training, 
                stochastic_training=stochastic_training,
                binary_test=binary_test, 
                stochastic_test=stochastic_test
            ))
            
    model = DeepCNN(rng = rng)
    
    print 'Creating the trainer'
    
    trainer = Trainer(rng = rng,
        train_set = train_set, valid_set = valid_set, test_set = test_set,
        model = model, load_path = load_path, save_path = save_path,
        zero_pad=zero_pad,
        affine_transform_a=affine_transform_a, # a is (more or less) the rotations
        affine_transform_b=affine_transform_b, # b is the translations
        horizontal_flip=horizontal_flip,
        LR = LR, LR_decay = LR_decay, LR_fin = LR_fin,
        M = M,
        BN = BN, BN_fast_eval=BN_fast_eval,
        batch_size = batch_size, number_of_batches_on_gpu = number_of_batches_on_gpu,
        n_epoch = n_epoch, monitor_step = monitor_step,
        shuffle_batches = shuffle_batches, shuffle_examples = shuffle_examples)
    
    print 'Building'
    
    trainer.build()
    
    print 'Training'
    
    start_time = time.clock()  
    trainer.train()
    end_time = time.clock()
    print 'The training took %i seconds'%(end_time - start_time)
    
    # print 'Save first hidden layer weights'
    
    # W = model.layer[1].W.get_value()
    # import pickle
    # pickle.dump( W, open( "W.pkl", "wb" ) )
    
    # print 'Display weights'
    
    # import matplotlib.pyplot as plt
    # import matplotlib.cm as cm
    # from filter_plot import tile_raster_images
    
    # W = np.transpose(model.layer[0].W.get_value())
    
    # print "min(W) = " + str(np.min(W))
    # print "max(W) = " + str(np.max(W))
    # print "mean(W) = " + str(np.mean(W))
    # print "mean(abs(W)) = " + str(np.mean(abs(W)))
    # print "var(W) = " + str(np.var(W))
    
    # plt.hist(W,bins=100)
    # plt.show()
    
    # W = tile_raster_images(W,(28,28),(5,5),(2, 2))
    # plt.imshow(W, cmap = cm.Greys_r)
    # plt.show()

