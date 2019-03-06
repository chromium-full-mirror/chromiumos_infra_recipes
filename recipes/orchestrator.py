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
    'recipe_engine/context',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/step',
    'cros_source',
    'dev',
    'git',
]

from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from recipe_engine.config import ConfigGroup
from recipe_engine.config import Single
from recipe_engine.recipe_api import Property

PROPERTIES = {
    # Specifies which refs in the manifest repository should point to the
    # snapshot ref used by the orchestrator, and when.
    'update_manifest_refs':
        Property(
            kind=ConfigGroup(
                # The start ref is updated before child builds are launched.
                start=Single(str)),
            default={},
        ),
}


def RunSteps(api, update_manifest_refs):
  # Set up source checkouts.
  api.cros_source.ensure_synced_cache()
  with api.cros_source.checkout_overlays_context():
    # Fetch snapshot refs and point start ref to the input snapshot.
    if 'start' in update_manifest_refs:
      with api.step.nest('update manifest start ref'):
        snapshot = api.buildbucket.gitiles_commit
        snapshot_path = api.cros_source.find_project_path(
            snapshot.project, 'master')
        with api.context(
            cwd=api.cros_source.workspace_path.join(snapshot_path)):
          api.git.fetch_ref(snapshot.host, snapshot.id)
          refspec = '%s:refs/heads/%s' % (snapshot.id,
                                          update_manifest_refs['start'])
          api.git.push(snapshot.host, refspec)

    requests = []
    # Just schedule a single child build to test postsubmit flow.
    # TODO(chromium:904935): Schedule all build targets.
    for builder in ['arm-generic-postsubmit']:
      requests.append(api.buildbucket.schedule_request(builder=builder))

    completed_builds = api.buildbucket.run(requests, timeout=60 * 60 * 4)
    for build in completed_builds:
      if build.status != common_pb2.SUCCESS:
        raise api.step.StepFailure('Child builder failed: {}'.format(
            build.builder))


def GenTests(api):
  yield (api.test('basic') + api.buildbucket.ci_build(
      project='chromeos', bucket='postsubmit',
      builder='postsubmit-orchestrator'))

  yield (api.test('updates refs') + api.buildbucket.ci_build(
      project='chromeos', bucket='postsubmit',
      builder='postsubmit-orchestrator') +
         api.properties(update_manifest_refs={'start': 'ref'}))

  yield api.test('child builder fails') + api.buildbucket.ci_build(
      project='chromeos', bucket='postsubmit', builder='postsubmit-orchestrator'
  ) + api.buildbucket.simulated_collect_output(
      [
          api.buildbucket.ci_build_message(build_id=8922054662172514000,
                                           status='FAILURE'),
      ],
      step_name='buildbucket.run.collect',
  )
