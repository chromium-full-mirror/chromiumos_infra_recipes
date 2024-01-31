# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe that builds factory images/artifacts on a factory branch."""

from contextlib import contextmanager

from PB.recipes.chromeos.build_factory import BuildFactoryProperties
from recipe_engine import post_process

DEPS = [
    'recipe_engine/context',
    'recipe_engine/properties',
    'build_menu',
    'src_state',
]


PROPERTIES = BuildFactoryProperties


class FactoryBuilder():
  """Class to contain useful information about the factory builder."""

  def __init__(self, api, props):
    """Set up a FactoryBuilder instance."""
    self.m = api
    self.props = props
    self._config = None

  def run(self):
    """Run the builder."""
    with self._setup():
      pass

  @contextmanager
  def _setup(self):
    """Context manager to configure the builder."""
    # If we do not have a gitiles_commit from buildbucket, use the manifest_branch
    # has manifest_branch, use that branch of the internal manifest.
    commit = self.m.src_state.gitiles_commit
    if not commit.project:
      commit = self.m.src_state.internal_manifest.as_gitiles_commit_proto
      commit.ref = 'refs/heads/{}'.format(self.props.manifest_branch)
    # TODO(b/241108061): Once factory builderconfigs have been created,
    # remove missing_ok=True.
    with self.m.build_menu.configure_builder(commit=commit, disable_sdk=True,
                                             targets=self.props.build_targets,
                                             missing_ok=True) as config:
      self._config = config
      with self.m.build_menu.setup_workspace(), \
          self.m.context(cwd=self.m.src_state.workspace_path):
        yield


def RunSteps(api, properties):
  FactoryBuilder(api, properties).run()


def GenTests(api):
  yield api.test('basic',
                 api.properties(manifest_branch='factory-brya-14909.B'),
                 api.post_process(post_process.DropExpectation))
