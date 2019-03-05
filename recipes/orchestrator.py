# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe that schedules child builders and watches for failures.

All builders run against the same source tree.

TODO(chromium:922994): Make this recipe somewhat generic across builders, e.g.
cq, postsubmit, release...
"""

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/step',
    'dev',
]


def RunSteps(api):
  api.dev.configure(dryrun=False)

  requests = []
  # Just schedule a single child build to test postsubmit flow.
  # TODO(chromium:904935): Schedule all build targets.
  for builder in ['arm-generic-postsubmit']:
    requests.append(api.buildbucket.schedule_request(builder=builder))

  completed_builds = api.buildbucket.run(requests)
  for build in completed_builds:
    if build.status != api.buildbucket.common_pb2.SUCCESS:
      raise api.step.StepFailure('Child builder failed: {}'.format(
          build.builder))


def GenTests(api):
  yield api.test('basic') + api.buildbucket.ci_build(
      project='chromeos', bucket='postsubmit',
      builder='postsubmit-orchestrator')

  yield api.test('child builder fails') + api.buildbucket.ci_build(
      project='chromeos', bucket='postsubmit', builder='postsubmit-orchestrator'
  ) + api.buildbucket.simulated_collect_output(
      [
          api.buildbucket.ci_build_message(build_id=8922054662172514000,
                                           status='FAILURE'),
      ],
      step_name='buildbucket.run.collect',
  )
