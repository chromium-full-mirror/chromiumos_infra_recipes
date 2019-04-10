# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/properties',
    'recipe_engine/step',
    'cros_build',
]

import contextlib


@contextlib.contextmanager
def execution_context(api, deferred):
  if deferred:
    with api.step.defer_results():
      yield
  else:
    yield


def get_result(step_result):
  if hasattr(step_result, 'get_result'):
    return step_result.get_result()

  return step_result


def RunSteps(api):
  deferred = api.properties.get('deferred', False)
  config = api.properties['config']
  scheduled = api.cros_build.schedule_child_builders('schedule', 'builder',
                                                     config)

  # Ensure build behavior works in deferred context
  with execution_context(api, deferred):
    collect_res = api.cros_build.collect(scheduled, step_name='collect')
    for completed_build in get_result(collect_res):
      api.cros_build.verify_builds([completed_build])
      api.cros_build.download_build_report(completed_build)


def GenTests(api):
  config = [dict(build_target='build_target', reference_design='ref_design')]

  contexts = ['non-deferred', 'deferred']

  for context in contexts:
    basic_build = api.cros_build.example(
      'basic_builder', config[0], build_target='bob')
    deferred = context == 'deferred'

    yield (api.test('%s.fail_collect' % context) + api.properties(
        config=config, deferred=deferred) + api.step_data('collect', retcode=1))

    yield (api.test('%s.basic' % context) + api.properties(
        config=config, deferred=deferred) +
           api.cros_build.simulated_collect_output([basic_build]))

    no_ref_config = [dict(build_target='build_target')]
    no_ref_build = api.cros_build.example('no_ref_builder', no_ref_config[0])
    yield (api.test('%s.no_ref_design' % context) + api.properties(
        config=no_ref_config, deferred=deferred) +
           api.cros_build.simulated_collect_output([no_ref_build]))

    failed_build = api.cros_build.example('failed_builder', config[0],
                                          status='FAILURE')
    yield (api.test('%s.fail_build' % context) + api.properties(
        config=config, deferred=deferred) +
           api.cros_build.simulated_collect_output([failed_build]))

    yield (api.test('%s.fail_download' % context) + api.properties(
        config=config,
        deferred=deferred) + api.cros_build.simulated_collect_output(
            [basic_build]) + api.cros_build.fail_download_report(basic_build))
