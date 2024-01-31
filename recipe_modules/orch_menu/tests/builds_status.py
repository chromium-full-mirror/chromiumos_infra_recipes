# -*- coding: utf-8 -*-
# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2

DEPS = [
    'recipe_engine/assertions',
    'failures',
    'orch_menu',
]



def RunSteps(api):
  # Set intial build status values.
  api.orch_menu.builds_status.completed_builds = [build_pb2.Build(id=111)]
  api.orch_menu.builds_status.running_builds = [
      build_pb2.Build(id=222), build_pb2.Build(id=333)
  ]
  api.orch_menu.builds_status.failures = [
      api.failures.Failure(kind='test', title='unchanged_failure', link_map={},
                           fatal=True, id='1'),
      api.failures.Failure(kind='test', title='updated_failure', link_map={},
                           fatal=True, id='2'),
  ]

  new_completed = [
      build_pb2.Build(id=111),
      build_pb2.Build(id=222),
  ]
  new_failures = [
      api.failures.Failure(kind='test', title='update_failure', link_map={},
                           fatal=False, id='2'),
      api.failures.Failure(kind='build', title='new_failure', link_map={},
                           fatal=True, id='3'),
  ]
  new_failures_copy = new_failures.copy()
  new_completed_copy = new_completed.copy()

  # Call the update function.
  api.orch_menu.builds_status.update(completed=new_completed,
                                     failures=new_failures)

  # Ensure inputs to update are not mutated.
  api.assertions.assertCountEqual(new_failures, new_failures_copy)
  api.assertions.assertCountEqual(new_completed, new_completed_copy)

  # Completed builds are deduped.
  api.assertions.assertCountEqual(api.orch_menu.builds_status.completed_builds,
                                  [
                                      build_pb2.Build(id=111),
                                      build_pb2.Build(id=222),
                                  ])
  # Completed builds are removed from running builds.
  api.assertions.assertCountEqual(api.orch_menu.builds_status.running_builds,
                                  [build_pb2.Build(id=333)])
  api.assertions.assertCountEqual(api.orch_menu.builds_status.failures, [
      api.failures.Failure(kind='test', title='unchanged_failure', link_map={},
                           fatal=True, id='1'),
      api.failures.Failure(kind='test', title='update_failure', link_map={},
                           fatal=False, id='2'),
      api.failures.Failure(kind='build', title='new_failure', link_map={},
                           fatal=True, id='3'),
  ])


def GenTests(api):

  yield api.test('basic')
