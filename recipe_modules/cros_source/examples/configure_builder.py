# -*- coding: utf-8 -*-
# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'cros_infra_config',
    'cros_source',
    'gerrit',
    'src_state',
]

from recipe_engine import post_process
from recipe_engine.recipe_api import StepFailure

from PB.chromiumos.builder_config import BuilderConfigs
from PB.go.chromium.org.luci.buildbucket.proto.common import (GerritChange,
                                                              GitilesCommit)
from PB.recipe_modules.chromeos.cros_source.cros_source import (
    CrosSourceProperties)
from PB.recipe_modules.chromeos.cros_source.examples.configure_builder import (
    ConfigureBuilderProperties)

PROPERTIES = ConfigureBuilderProperties


def RunSteps(api, properties):
  api.cros_source.configure_builder()
  api.assertions.assertEqual(api.src_state.gitiles_commit,
                             properties.expected_commit)


def GenTests(api):

  host = 'chromium.googlesource.com'
  project = 'project'
  branch = 'firmware-board-11111.B'
  revision = '{}-HEAD-SHA'.format(branch)
  refspec = 'refs/heads/{}'.format(branch)

  R90_branch = 'release-R90-13816.B'
  R90_revision = '{}-HEAD-SHA'.format(R90_branch)
  R90_refspec = 'refs/heads/{}'.format(R90_branch)

  stabilize_branch = 'stabilize-13817.B'
  stabilize_revision = '{}-HEAD-SHA'.format(stabilize_branch)
  stabilize_refspec = 'refs/heads/{}'.format(stabilize_branch)

  manifest_branch = 'snapshot'

  def _change(change_num, project='project', patchset=7):
    return GerritChange(host='chromium.googlesource.com', project=project,
                        change=change_num, patchset=patchset)

  def _gerrit_return(changes, name='configure builder', values_dict=None):
    values_dict = values_dict or {}
    return api.gerrit.set_gerrit_fetch_changes_response(name, changes,
                                                        values_dict)

  def props(host=None, project=None, ref=None, id=None):
    host = host or api.src_state.internal_manifest.host
    project = project or api.src_state.internal_manifest.project
    ref = ref or api.src_state.internal_manifest.ref
    id = id or api.src_state.internal_manifest.id
    commit = GitilesCommit(host=host, project=project, ref=ref, id=id)
    return api.properties(ConfigureBuilderProperties(expected_commit=commit))

  change1 = _change(555)
  change2 = _change(556)
  conf_change1 = _change(557, project='chromeos/infra/config', patchset=1)
  conf_change2 = _change(558, project='chromeos/infra/config', patchset=1)

  yield api.cros_source.test(
      'basic', manifest_branch,
      props(ref='refs/heads/snapshot', id='snapshot-HEAD-SHA'),
      api.post_check(post_process.StatusSuccess), gerrit_changes=[change1],
      revision=None)

  yield api.cros_source.test(
      'change-on-branch', manifest_branch, props(ref=refspec, id=revision),
      api.post_check(post_process.StatusSuccess),
      _gerrit_return([change1], values_dict={555: dict(branch=branch)}),
      gerrit_changes=[change1], revision=None)

  yield api.cros_source.test(
      'change-on-two-branches', manifest_branch, props(ref=refspec,
                                                       id=revision),
      api.post_check(post_process.StatusSuccess),
      _gerrit_return([change1, change2], values_dict={
          555: dict(branch=branch),
          556: dict(branch=branch + '-main')
      }), gerrit_changes=[change1, change2], revision=None)

  yield api.cros_source.test(
      'change-on-diff-branches', manifest_branch, props(ref=refspec,
                                                        id=revision),
      api.post_check(post_process.StatusSuccess),
      _gerrit_return([change1, change2], values_dict={
          555: dict(branch=branch),
          556: dict(branch='firmware-other-999.B')
      }), gerrit_changes=[change1, change2], revision=None)

  yield api.cros_source.test(
      'conf-change', manifest_branch,
      props(ref='refs/heads/snapshot', id='snapshot-HEAD-SHA'),
      api.post_check(post_process.StatusSuccess),
      api.cros_infra_config.override_builder_configs_test_data(
          BuilderConfigs(), ref='refs/changes/57/557/1', binaryproto=False,
          step_name='configure builder.cros_infra_config'),
      api.post_check(
          post_process.MustRun,
          'configure builder.cros_infra_config.read builder configs.'
          'fetch refs/changes/57/557/1:generated/builder_configs.cfg'),
      gerrit_changes=[conf_change1], revision=None)

  yield api.cros_source.test('two-conf-change',
                             api.post_check(post_process.StatusFailure),
                             gerrit_changes=[conf_change1,
                                             conf_change2], revision=None)

  yield api.cros_source.test(
      'change-on-release-branch', manifest_branch,
      props(ref=R90_refspec, id=R90_revision),
      api.post_check(post_process.StatusSuccess),
      _gerrit_return([change1], values_dict={555: dict(branch=R90_branch)}),
      gerrit_changes=[change1], revision=None)

  yield api.cros_source.test(
      'change-on-stabilize-branch', manifest_branch,
      props(ref=stabilize_refspec, id=stabilize_revision),
      api.post_check(post_process.StatusSuccess),
      _gerrit_return([change1],
                     values_dict={555: dict(branch=stabilize_branch)}),
      gerrit_changes=[change1], revision=None)
