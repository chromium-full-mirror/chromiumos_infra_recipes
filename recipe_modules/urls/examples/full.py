# -*- coding: utf-8 -*-
# Copyright 2018 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Basic tests for the urls recipe module."""

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.test_platform.taskstate import TaskState

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/step',
    'skylab_results',
    'urls',
]



def RunSteps(api):
  build = build_pb2.Build(id=123)
  api.assertions.assertEqual(
      api.urls.get_build_link_map(build),
      {'build page': api.buildbucket.build_url(build_id=123)})

  build = build_pb2.Build(id=123)
  api.assertions.assertEqual(
      api.urls.get_vm_test_link_map(build),
      {'test page': api.buildbucket.build_url(build_id=123)})

  skylab_task = api.skylab_results.test_api.skylab_task(url='skylab.whatever')
  api.assertions.assertEqual(
      api.urls.get_skylab_task_url(skylab_task), 'skylab.whatever')


  api.assertions.assertEqual(
      api.urls.get_gs_path_url('gs://bucket/a/b/c'),
      'https://storage.cloud.google.com/bucket/a/b/c')
  # Test a path where the bucket starts with 'gs', to make sure it doesn't
  # get stripped as well.
  api.assertions.assertEqual(
      api.urls.get_gs_path_url('gs://gs-test/a/b'),
      'https://storage.cloud.google.com/gs-test/a/b')
  api.assertions.assertRaises(ValueError, api.urls.get_gs_path_url, 'a/b/c')

  api.assertions.assertEqual(
      api.urls.get_gs_bucket_url('bucket-name', 'path/to/file'),
      'https://console.cloud.google.com/storage/browser/_details/' +
      'bucket-name/path/to/file')

  task_state = TaskState(life_cycle=TaskState.LIFE_CYCLE_ABORTED,
                         verdict=TaskState.VERDICT_FAILED)
  api.assertions.assertEqual(
      api.urls.get_state_suffix(task_state), ' (canceled while running)')
  for life_cycle in [
      TaskState.LIFE_CYCLE_CANCELLED, TaskState.LIFE_CYCLE_RUNNING,
      TaskState.LIFE_CYCLE_ABORTED, TaskState.LIFE_CYCLE_REJECTED,
      TaskState.LIFE_CYCLE_PENDING
  ]:
    api.urls.get_state_suffix(
        TaskState(life_cycle=life_cycle, verdict=TaskState.VERDICT_FAILED))

  with api.step.nest('outer step') as pres:
    step_result = api.step('run cmd on a/b', ['ls'])
    pres.logs['customlog'] = 'new info'
    api.assertions.assertEqual(
        api.urls.get_logdog_url(step_result, 'customlog',
                                use_top_level_step=True),
        'https://logs.chromium.org/logs/chromeos/logdog/prefix/+/u/outer_step/customlog',
    )
    api.assertions.assertEqual(
        api.urls.get_logdog_url(step_result, 'customlog',
                                use_top_level_step=False),
        'https://logs.chromium.org/logs/chromeos/logdog/prefix/+/u/outer_step/run_cmd_on_a_b/customlog',
    )


def GenTests(api):
  # Populate logdog fields on the build message so link components are filled
  # out.
  build_message = api.buildbucket.ci_build_message(build_id=123)
  build_message.infra.logdog.hostname = 'logs.chromium.org'
  build_message.infra.logdog.project = 'chromeos'
  build_message.infra.logdog.prefix = 'logdog/prefix'

  yield api.test(
      'basic',
      api.buildbucket.build(build_message),
  )
