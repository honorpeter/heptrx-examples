#!/usr/bin/env python

# System imports
import os
import math
import logging
import argparse

# External imports
import numpy as np
import matplotlib
matplotlib.use('AGG')
import matplotlib.pyplot as plt

# Local imports
from metrics import calc_hit_accuracy
from toydata import generate_data, track_hit_coords
from drawing import (draw_layers, draw_projections, draw_3d_event,
                     draw_train_history)


def parse_args():
    """Parse the command line arguments"""
    parser = argparse.ArgumentParser('simpleLSTM_2D')
    add_arg = parser.add_argument
    add_arg('-m', '--model', default='default',
            choices=['default', 'deep', 'bilstm'],
            help='Name the model to use')
    add_arg('-z', '--num-hidden', type=int, default=512,
            help='Size of hidden dimensions')
    add_arg('-n', '--num-train', type=int, default=640000,
            help='Number of events to simulate for training')
    add_arg('-e', '--num-epoch', type=int, default=10,
            help='Number of epochs in which to record training history')
    add_arg('-t', '--num-test', type=int, default=51200,
            help='Number of events to simulate for testing')
    add_arg('-b', '--batch-size', type=int, default=128,
            help='Training batch size')
    add_arg('-o', '--output-dir',
            help='Directory to save model and plots')
    add_arg('--num-det-layer', type=int, default=10,
            help='Number of detector layers')
    add_arg('--det-layer-size', type=int, default=32,
            help='Width of the detector layers in pixels')
    add_arg('--num-seed-layer', type=int, default=3,
            help='Number of track seeding detector layers')
    add_arg('--avg-bkg-tracks', type=int, default=3)
    add_arg('--noise-prob', type=float, default=0.01)
    return parser.parse_args()

def batch_generator(num_batch, det_shape, num_seed_layers,
                    avg_bkg_tracks, noise_prob):
    """Generator of toy data batches for training"""
    shape = (num_batch,) + det_shape
    while True:
        events, sig_tracks, _ = generate_data(
                shape, num_seed_layers=num_seed_layers,
                avg_bkg_tracks=avg_bkg_tracks,
                noise_prob=noise_prob, verbose=False)
        yield (flatten_layers(events), flatten_layers(sig_tracks))

def flatten_layers(data):
    """Flattens each 2D detector layer into a 1D array"""
    return data.reshape((data.shape[0], data.shape[1], -1))

def plot_event(event, pred, track, params, output_dir, file_prefix,
               num_det_layer):
    """Make plots for one event"""
    # Get the track hit coordinates
    sigx, sigy = track_hit_coords(params, np.arange(num_det_layer),
                                  as_type=np.float32)
    # Draw model inputs
    filename = os.path.join(output_dir, file_prefix + '_inputs.png')
    draw_layers(event, truthx=sigx, truthy=sigy).savefig(filename)
    # Draw model outputs
    filename = os.path.join(output_dir, file_prefix + '_outputs.png')
    draw_layers(pred, truthx=sigx, truthy=sigy).savefig(filename)
    # Draw input projections
    filename = os.path.join(output_dir, file_prefix + '_inputProj.png')
    draw_projections(event, truthx=sigx, truthy=sigy).savefig(filename)
    # Draw output projections
    filename = os.path.join(output_dir, file_prefix + '_outputProj.png')
    draw_projections(pred, truthx=sigx, truthy=sigy).savefig(filename)
    # Draw the 3D plot
    filename = os.path.join(output_dir, file_prefix + '_plot3d.png')
    fig, ax = draw_3d_event(event, track, params, pred,
                            pred_threshold=0.01)
    fig.savefig(filename)
    plt.close('all')

def main():

    args = parse_args()

    from models import build_lstm_model, build_deep_lstm_model, build_bilstm_model

    # Logging
    logging.basicConfig(level=logging.INFO,
                        format='%(asctime)s %(levelname)s %(message)s')
    logging.info('Initializing')

    # Configuration
    logging.info('Configuring with options: %s' % args)
    det_shape = (args.num_det_layer, args.det_layer_size, args.det_layer_size)
    logging.info('Detector shape: %s' % (det_shape,))
    
    # Random seed
    np.random.seed(2017)

    # Build the model
    logging.info('Building model')
    model_map = dict(default=build_lstm_model, deep=build_deep_lstm_model,
                     bilstm=build_bilstm_model)
    model_func = model_map[args.model]
    model = model_func(args.num_det_layer, args.det_layer_size**2,
                       hidden_dim=args.num_hidden)
    model.summary()
    
    # Train the model
    logging.info('Training the model')
    events_per_epoch = args.num_train / args.num_epoch
    bgen = batch_generator(args.batch_size, det_shape, args.num_seed_layer,
                           args.avg_bkg_tracks, args.noise_prob)
    history = model.fit_generator(bgen, samples_per_epoch=events_per_epoch,
                                  nb_epoch=args.num_epoch)
    logging.info('')

    # Create a test set
    logging.info('Creating a test set')
    seed_max = 4294967295
    np.random.seed(hash('HEP.TrkX') % seed_max)
    test_events, test_tracks, test_params = generate_data(
            (args.num_test,) + det_shape, num_seed_layers=args.num_seed_layer,
            avg_bkg_tracks=args.avg_bkg_tracks, noise_prob=args.noise_prob,
            verbose=False)
    test_input = flatten_layers(test_events)
    test_target = flatten_layers(test_tracks)

    # Run model on the test set
    logging.info('Processing the test set')
    test_preds = model.predict(test_input, batch_size=args.batch_size)

    # Evaluate performance
    pixel_accuracy = calc_hit_accuracy(test_preds, test_target,
                                       num_seed_layers=args.num_seed_layer)
    # Hit classification accuracy
    test_scores = test_preds * flatten_layers(test_events)
    hit_accuracy = calc_hit_accuracy(test_scores, test_target,
                                     num_seed_layers=args.num_seed_layer)
    logging.info('Accuracy of predicted pixel: %g' % pixel_accuracy)
    logging.info('Accuracy of classified hit: %g' % hit_accuracy)

    if args.output_dir is not None:
        logging.info('Saving outputs to %s' % args.output_dir)

        # Save the model to hdf5
        model.save(os.path.join(args.output_dir, 'model.h5'))

        # Plot training history
        filename = os.path.join(args.output_dir, 'training.png')
        draw_train_history(history, draw_val=False).savefig(filename)

        # Plot the first 5 events from the test set
        for i in range(5):
            event, track, params = test_events[i], test_tracks[i], test_params[i]
            pred = test_preds[i].reshape(det_shape)
            plot_event(event, pred, track, params,
                       args.output_dir, 'ev%i' % i,
                       args.num_det_layer)

    logging.info('All done!')

if __name__ == '__main__':
    main()
