# -*- coding: utf-8 -*-

# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/cq',
    'cros_history',
]



def RunSteps(api):
  previous_builds = api.cros_history.get_matching_builds(
      api.buildbucket.build, statuses=[common_pb2.STARTED], start_build_id=83)
  api.assertions.assertEqual(1, len(previous_builds))


def GenTests(api):

  def build_msg(build_id, create_time):
    message = api.buildbucket.try_build_message(project='chromeos', bucket='cq',
                                                builder='bojack-cq',
                                                status='STARTED',
                                                build_id=build_id)
    message.create_time.seconds = create_time
    return message

  yield api.test(
      'basic', api.buildbucket.build(build_msg(400, create_time=400)),
      api.cq(run_mode=api.cq.FULL_RUN),
      api.buildbucket.simulated_search_results(
          [build_msg(100, create_time=100)],
          'find matching builds.buildbucket.search'))
