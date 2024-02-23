# -*- coding: utf-8 -*-
# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests to test e2e coverage uploads."""

from recipe_engine import post_process

DEPS = [
    'recipe_engine/file',
    'recipe_engine/raw_io',
    'recipe_engine/swarming',
    'build_menu',
    'code_coverage',
]



def RunSteps(api):
  with api.build_menu.configure_builder(
  ), api.build_menu.setup_workspace_and_chroot():
    api.build_menu.setup_sysroot_and_determine_relevance()
    api.build_menu.bootstrap_sysroot()
    api.build_menu.install_packages()
    api.build_menu.build_and_test_images()
    api.code_coverage.update_e2e_metadata('chromeos-image-archive',
                                          'buildername/id', 'brya',
                                          'R123-15527.0.0-13245678')


def GenTests(api):
  yield api.build_menu.test(
      'e2e-uploads-metadata',
      api.step_data(
          'gsutil ls snapshot version', stdout=api.raw_io.output_text('''
            gs://chromeos-image-archive/brya-snapshot/8766842719767962417/
        '''), retcode=0),
      api.post_check(post_process.MustRun, 'upload e2e coverage metadata'),
      api.post_check(post_process.MustRun,
                     'upload e2e coverage metadata.add e2e coverage metadata'))

  yield api.build_menu.test(
      'upload-active-version-no-date',
      api.step_data('verify active version.read current active version',
                    api.file.read_text('{"date":""}')),
      api.post_check(post_process.MustRun,
                     'verify active version.gsutil download'),
      api.post_check(
          post_process.DoesNotRun,
          'verify active version.upload active version(found date diff)'))

  yield api.build_menu.test(
      'snapshot-version',
      api.
      post_check(post_process.StepCommandContains, 'gsutil ls snapshot version', [
          'gs://chromeos-image-archive/brya-snapshot/R123-15527.0.0-13245678*/image.zip'
      ]),
      api.step_data(
          'gsutil ls snapshot version', stdout=api.raw_io.output_text('''
            gs://chromeos-image-archive/brya-snapshot/8766842719767962417/
        '''), retcode=0),
      api.post_check(post_process.MustRun, 'upload e2e coverage metadata'))
