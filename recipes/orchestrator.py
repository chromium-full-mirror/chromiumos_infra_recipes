# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe that schedules child builders and watches for failures.

All builders run against the same source tree.
"""

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/step',
    'cros_source',
    'cros_version',
    'dev',
    'git',
    'infra_config',
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
                # An example start ref is 'postsubmit', which should update
                # right when the orchestrator launches.
                start=Single(str),

                # The success ref is updated only if all child builds succeed.
                # An example success ref is 'stable', which should update only
                # when postsubmit builds succeed.
                success=Single(str),
            ),
            default={},
        ),
}


def RunSteps(api, update_manifest_refs):
  validate_refs(update_manifest_refs.values())

  # Set up source checkouts.
  api.cros_source.ensure_synced_cache()
  with api.cros_source.checkout_overlays_context():
    # Point start ref to the input snapshot if specified.
    maybe_update_manifest_ref(api, update_manifest_refs, 'start')

    # Calculate buildspec.
    # TODO(lannm): Increment rc and push to manifest-versions.
    api.cros_version.read_workspace_version()

    requests = []

    orchestrator_builder_config = api.infra_config.get_builder_config(
        api.buildbucket.build.builder.builder)
    for child in orchestrator_builder_config.orchestrator.children:
      requests.append(api.buildbucket.schedule_request(builder=child))

    completed_builds = api.buildbucket.run(requests, timeout=60 * 60 * 4)
    for build in completed_builds:
      # TODO(chromium:924657): Consider builder criticality.
      if build.status != common_pb2.SUCCESS:
        raise api.step.StepFailure('Child builder failed: {}'.format(
            build.builder))

    # Victory! If we've made it this far, the child builders were successful
    # and we can update the success manifest ref if it is specified.
    maybe_update_manifest_ref(api, update_manifest_refs, 'success')


def validate_refs(refs):
  """Assert all given refs start with refs/heads.

  Args:
    refs (list[str]): Refs to validate.

  Raises:
    AssertionError: If any invalid ref is found.
  """
  for ref in refs:
    if not ref.startswith('refs/heads/'):
      raise ValueError('ref %s is missing refs/heads/' % ref)


def maybe_update_manifest_ref(api, update_manifest_refs, ref_key):
  """Update ref in manifest-internal to point to current snapshot.

  Args:
    api (object): See RunSteps documentation.
    update_manifest_refs (dict): Maps ref key (e.g. start) to qualified ref.
    ref_key: Key for ref to access in update_manifest_refs.
  """
  if ref_key in update_manifest_refs:
    with api.step.nest('update manifest %s ref' % ref_key):
      snapshot = api.buildbucket.gitiles_commit
      snapshot_path = api.cros_source.find_project_path(snapshot.project,
                                                        'master')
      with api.context(cwd=api.cros_source.workspace_path.join(snapshot_path)):
        git_repo = 'https://%s/%s' % (snapshot.host, snapshot.project)
        api.git.fetch_ref(git_repo, snapshot.id)
        refspec = '%s:%s' % (snapshot.id, update_manifest_refs[ref_key])
        api.git.push(git_repo, refspec)


def GenTests(api):
  yield (api.test('basic') + api.buildbucket.ci_build(
      project='chromeos', bucket='postsubmit',
      builder='postsubmit-orchestrator'))

  yield (api.test('updates refs') + api.buildbucket.ci_build(
      project='chromeos', bucket='postsubmit',
      builder='postsubmit-orchestrator') + api.properties(update_manifest_refs={
          'start': 'refs/heads/foo',
          'success': 'refs/heads/bar'
      }))

  yield (api.test('bad update ref') +
         api.properties(update_manifest_refs={'start': 'foo'}) +
         api.expect_exception("ValueError"))

  yield (api.test('child builder fails') + api.buildbucket.ci_build(
      project='chromeos', bucket='postsubmit',
      builder='postsubmit-orchestrator') +
         api.buildbucket.simulated_collect_output(
             [
                 api.buildbucket.ci_build_message(build_id=8922054662172514000,
                                                  status='FAILURE'),
                 api.buildbucket.ci_build_message(build_id=8922054662172514001,
                                                  status='SUCCESS'),
             ],
             step_name='buildbucket.run.collect',
         ))
