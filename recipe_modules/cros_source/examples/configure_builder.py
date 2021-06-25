# -*- coding: utf-8 -*-
# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
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

  yield api.cros_source.test(
      'basic', props(ref='refs/heads/snapshot', id='snapshot-HEAD-SHA'),
      api.post_check(post_process.StatusSuccess), gerrit_changes=[change1],
      revision=None)

  yield api.cros_source.test(
      'change-on-branch', props(ref=refspec, id=revision),
      api.post_check(post_process.StatusSuccess),
      _gerrit_return([change1], values_dict={555: dict(branch=refspec)}),
      gerrit_changes=[change1], revision=None)

  yield api.cros_source.test(
      'change-on-two-branches', props(ref=refspec, id=revision),
      api.post_check(post_process.StatusSuccess),
      _gerrit_return([change1, change2], values_dict={
          555: dict(branch=refspec),
          556: dict(branch=refspec + '-main')
      }), gerrit_changes=[change1, change2], revision=None)

  yield api.cros_source.test(
      'change-on-diff-branches', props(ref=refspec, id=revision),
      api.post_check(post_process.StatusSuccess),
      _gerrit_return(
          [change1, change2], values_dict={
              555: dict(branch=refspec),
              556: dict(branch='refs/heads/firmware-other-999.B')
          }), gerrit_changes=[change1, change2], revision=None)
