# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests to verify dlc_utils.get_dlcs_in_path."""

from recipe_engine import post_process
from recipe_engine.recipe_api import Property

DEPS = [
    'depot_tools/gsutil',
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'dlc_utils',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'

PROPERTIES = {'expected_locations': Property(default=[])}


def RunSteps(api, expected_locations):
  api.assertions.assertEqual(
      expected_locations,
      api.dlc_utils.get_dlcs_in_path(
          'gs://chromeos-image-archive/brya-release/R108-15132.0.0/'))


def GenTests(api):

  yield api.test(
      'pulls-from-default-directory',
      api.properties(expected_locations=[
          'gs://chromeos-image-archive/brya-release/R108-15132.0.0/dlc/borealis-dlc/package/dlc.img',
          'gs://chromeos-image-archive/brya-release/R108-15132.0.0/dlc/handwriting-da/package/dlc.img',
      ]), mock_dlc(api), api.post_process(post_process.DropExpectation))

  yield api.test(
      'pulls-from-additional-directories',
      api.properties(
          expected_locations=[
              'gs://chromeos-image-archive/brya-release/R108-15132.0.0/dlc/borealis-dlc/package/dlc.img',
              'gs://chromeos-image-archive/brya-release/R108-15132.0.0/dlc/handwriting-da/package/dlc.img',
              'gs://chromeos-image-archive/brya-release/R108-15132.0.0/dlc-scaling/borealis-dlc2/package/dlc.img',
              'gs://chromeos-image-archive/brya-release/R108-15132.0.0/dlc-scaling/handwriting-de/package/dlc.img',
          ], **{
              '$chromeos/dlc_utils': {
                  'dlc_directories': ['dlc', 'dlc-scaling']
              }
          }), mock_dlc(api), mock_dlc_scaling(api),
      api.post_process(post_process.DropExpectation))

  yield api.test(
      'handles-empty-directories',
      api.properties(
          expected_locations=[
              'gs://chromeos-image-archive/brya-release/R108-15132.0.0/dlc/borealis-dlc/package/dlc.img',
              'gs://chromeos-image-archive/brya-release/R108-15132.0.0/dlc/handwriting-da/package/dlc.img',
          ], **{
              '$chromeos/dlc_utils': {
                  'dlc_directories': ['dlc', 'dlc-scaling']
              }
          }), mock_dlc(api), mock_dlc_scaling(api, failed=True),
      api.post_process(post_process.DropExpectation))

  yield api.test(
      'pulls-from-additional-filenames',
      api.properties(
          expected_locations=[
              'gs://chromeos-image-archive/brya-release/R108-15132.0.0/dlc/borealis-dlc/package/dlc.img',
              'gs://chromeos-image-archive/brya-release/R108-15132.0.0/dlc/borealis-dlc/package/meta/imageloader.json',
              'gs://chromeos-image-archive/brya-release/R108-15132.0.0/dlc/handwriting-da/package/dlc.img',
              'gs://chromeos-image-archive/brya-release/R108-15132.0.0/dlc/handwriting-da/package/meta/imageloader.json',
              'gs://chromeos-image-archive/brya-release/R108-15132.0.0/dlc-scaling/borealis-dlc2/package/dlc.img',
              'gs://chromeos-image-archive/brya-release/R108-15132.0.0/dlc-scaling/borealis-dlc2/package/meta/imageloader.json',
              'gs://chromeos-image-archive/brya-release/R108-15132.0.0/dlc-scaling/handwriting-de/package/dlc.img',
              'gs://chromeos-image-archive/brya-release/R108-15132.0.0/dlc-scaling/handwriting-de/package/meta/imageloader.json',
          ], **{
              '$chromeos/dlc_utils': {
                  'dlc_directories': ['dlc', 'dlc-scaling'],
                  'dlc_file_names': ['dlc.img', 'imageloader.json']
              }
          }), mock_dlc(api), mock_dlc_scaling(api),
      api.post_process(post_process.DropExpectation))


def mock_dlc(api):
  return api.step_data(
      'gsutil ls dlc', stdout=api.raw_io.output_text("""
gs://chromeos-image-archive/brya-release/R108-15132.0.0/dlc/borealis-dlc/package/dlc.img
gs://chromeos-image-archive/brya-release/R108-15132.0.0/dlc/borealis-dlc/package/meta/imageloader.json
gs://chromeos-image-archive/brya-release/R108-15132.0.0/dlc/borealis-dlc/package/meta/table
gs://chromeos-image-archive/brya-release/R108-15132.0.0/dlc/borealis-dlc/package/root/credits.html
gs://chromeos-image-archive/brya-release/R108-15132.0.0/dlc/borealis-dlc/package/root/splash_logo.png
gs://chromeos-image-archive/brya-release/R108-15132.0.0/dlc/borealis-dlc/package/root/vm_kernel
gs://chromeos-image-archive/brya-release/R108-15132.0.0/dlc/borealis-dlc/package/root/vm_rootfs.img
gs://chromeos-image-archive/brya-release/R108-15132.0.0/dlc/handwriting-da/package/dlc.img
gs://chromeos-image-archive/brya-release/R108-15132.0.0/dlc/handwriting-da/package/meta/imageloader.json
gs://chromeos-image-archive/brya-release/R108-15132.0.0/dlc/handwriting-da/package/meta/table
gs://chromeos-image-archive/brya-release/R108-15132.0.0/dlc/handwriting-da/package/root/compact.fst.local
gs://chromeos-image-archive/brya-release/R108-15132.0.0/dlc/handwriting-da/package/root/latin_indy.tflite
      """), retcode=0)


def mock_dlc_scaling(api, failed=False):
  if failed:
    return api.step_data('gsutil ls dlc-scaling',
                         stdout=api.raw_io.output_text(""), retcode=1)
  return api.step_data(
      'gsutil ls dlc-scaling', stdout=api.raw_io.output_text("""
gs://chromeos-image-archive/brya-release/R108-15132.0.0/dlc-scaling/borealis-dlc2/package/dlc.img
gs://chromeos-image-archive/brya-release/R108-15132.0.0/dlc-scaling/borealis-dlc2/package/meta/imageloader.json
gs://chromeos-image-archive/brya-release/R108-15132.0.0/dlc-scaling/borealis-dlc2/package/meta/table
gs://chromeos-image-archive/brya-release/R108-15132.0.0/dlc-scaling/borealis-dlc2/package/root/credits.html
gs://chromeos-image-archive/brya-release/R108-15132.0.0/dlc-scaling/borealis-dlc2/package/root/splash_logo.png
gs://chromeos-image-archive/brya-release/R108-15132.0.0/dlc-scaling/borealis-dlc2/package/root/vm_kernel
gs://chromeos-image-archive/brya-release/R108-15132.0.0/dlc-scaling/borealis-dlc2/package/root/vm_rootfs.img
gs://chromeos-image-archive/brya-release/R108-15132.0.0/dlc-scaling/handwriting-de/package/dlc.img
gs://chromeos-image-archive/brya-release/R108-15132.0.0/dlc-scaling/handwriting-de/package/meta/imageloader.json
gs://chromeos-image-archive/brya-release/R108-15132.0.0/dlc-scaling/handwriting-de/package/meta/table
gs://chromeos-image-archive/brya-release/R108-15132.0.0/dlc-scaling/handwriting-de/package/root/compact.fst.local
gs://chromeos-image-archive/brya-release/R108-15132.0.0/dlc-scaling/handwriting-de/package/root/latin_indy.tflite
      """), retcode=0)
