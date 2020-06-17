# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API providing a menu for orchestrator steps"""

import collections
import contextlib

from google.protobuf import json_format

from recipe_engine import recipe_api

from PB.chromiumos.builder_config import BuilderConfig
from PB.go.chromium.org.luci.buildbucket.proto.common import GitilesCommit
from PB.recipes.chromeos.orchestrator import OrchestratorProperties

_manifest_info = collections.namedtuple(
    '_manifest_info', ['name', 'gitiles_commit', 'path', 'url'])


class OrchMenuApi(recipe_api.RecipeApi):
  """A module with steps used by orchestrators.

  Orchestrators do not call other recipe modules directly: they always get there
  via this module, and are a simple sequence of steps.
  """

  # TODO(crbug/1053703): Make the above statement true.

  def initialize(self):
    self._orchestrator_properties = json_format.ParseDict(
        self.m.buildbucket.build.input.properties, OrchestratorProperties(),
        ignore_unknown_fields=True)
    self._has_manifest_refs = False
    self._internal_repo_path = None
    self._external_repo_path = None
    self._external_gitiles_commit = None

    # Set the buildbucket host for our children to use.
    self.m.buildbucket.host = self.m.buildbucket.HOST_PROD_BEEFY

  @property
  def config(self):
    return self.m.cros_infra_config.config

  @property
  def gitiles_commit(self):
    return self.m.cros_infra_config.gitiles_commit

  @property
  def gerrit_changes(self):
    return self.m.cros_infra_config.gerrit_changes

  def get_manifest_info(self, external=False):
    """Return information about a manifest repo.

    Args:
      external (bool): Whether the external manifest is wanted.

    Returns:
      None, or an object with attributes:
        name (str): display name for the manifest repo.
        gitiles_commit (GitilesCommit): commit for the repo.
        path (Path): Path to the checked out repo.
        url (str): URL for the repo.
    """
    if external:
      return _manifest_info(
          'manifest', self._external_gitiles_commit, self._external_repo_path,
          self.m.gitiles.repo_url(self._external_gitiles_commit))
    else:
      return _manifest_info('manifest-internal', self.gitiles_commit,
                            self._internal_repo_path,
                            self.m.gitiles.repo_url(self.gitiles_commit))

  @contextlib.contextmanager
  def setup_orchestrator(self, missing_ok=False, test_footers=None):
    """Initial setup steps for the orchestrator.

    This context manager returns with all of the contexts that the orchestrator
    needs to have when it runs, for cleanup to happen properly.

    Args:
      missing_ok (bool): Whether it is OK if no config is found.
      test_footers (str): test Cr-External-Snapshot footer data(values separated
          by newlines), or None.

    Returns:
      BuilderConfig or None, with an active context.
    """
    properties = self._orchestrator_properties
    with self.m.bot_cost.cq_run_cost_context():
      with self.m.step.nest('set up orchestrator') as presentation:
        self._validate_properties(properties)
        config = self.m.cros_infra_config.configure_builder(
            self.m.buildbucket.gitiles_commit,
            self.m.buildbucket.build.input.gerrit_changes)

        self.m.cros_bisect.set_orchestrator_bisect_builder()
        presentation.links['manifest snapshot revision'] = (
            self.m.gitiles.file_url(self.gitiles_commit, 'snapshot.xml'))

        # If updating manifests, clone the internal manifest repo.
        if self._has_manifest_refs:
          self._internal_repo_path = self.clone_repo('internal manifest',
                                                     self.gitiles_commit)

          test_footers = test_footers or 'External-Snapshot-SHA'
          # Read the Cr-External-Snapshot footer to get ref of external snapshot
          # that corresponds with the internal snapshot.
          with self.m.context(cwd=self._internal_repo_path):
            footer_values = self.m.git_footers.from_ref(
                self.gitiles_commit.id, key='Cr-External-Snapshot',
                step_test_data=self.m.git_footers.test_api
                .step_test_data_factory(test_footers))

            # Make sure we got exactly one snapshot ref.
            if not footer_values or len(footer_values) != 1:
              raise self.m.step.StepFailure(
                  'expected exactly one Cr-External-Snapshot footer')
            extern_snapshot_id = footer_values[0]

          self._external_gitiles_commit = GitilesCommit(
              host=self.m.cros_source.EXTERNAL_HOST,
              project=self.m.cros_source.EXTERNAL_PROJECT,
              ref=self.gitiles_commit.ref, id=extern_snapshot_id)

          # clone the external manifest repo
          self._external_repo_path = self.clone_repo(
              'external manifest', self._external_gitiles_commit)

        if not config and not missing_ok:
          raise self.m.step.StepFailure('Missing configuration for {}'.format(
              self.m.buildbucket.builder_name))

      # Yield while inside of the bot_cost.cq_run_cost_context.
      yield config

  def _validate_properties(self, properties):
    """Validate the orchestrator properties.

    Args:
      properties (OrchestratorProperties): The properties for the orchestrator.

    Raises:
      StepFailure on errors.
    """
    # The only property we need to validate is update_manifest_refs, and we want
    # to validate all of them.
    manifest_refs = json_format.MessageToDict(properties.update_manifest_refs,
                                              preserving_proto_field_name=True)

    for ref, value in manifest_refs.items():
      if not value.startswith('refs/heads/'):
        raise self.m.step.StepFailure('%s ref %s is missing refs/heads/' %
                                      (ref, value))
      self._has_manifest_refs = True

  def clone_repo(self, name, commit):
    """Clone a repo into a temporary directory.

    Args:
      name (str): Display name for the repo.
      commit (GitilesCommit): The commit to clone (and fetch).

    Returns:
      (Path) path of the repo.
    """
    path = self.m.path.mkdtemp()
    url = self.m.gitiles.repo_url(commit)
    with self.m.step.nest('clone %s repo' % name), self.m.context(cwd=path):
      self.m.git.clone(url, timeout_sec=60 * 60)
      if commit.id:
        self.m.git.fetch_ref(url, commit.id, timeout_sec=60 * 60)
    return path

  def push_manifest_refs(self, ref):
    """Update the remote ref (if any).

    If |ref| evaluates to False, do nothing.

    Args:
      ref (str): Ref to push to (possibly empty) or None
    """
    if ref:
      for external in False, True:
        manifest = self.get_manifest_info(external)
        with self.m.step.nest('update %s ref %s' % (manifest.name, ref)), \
            self.m.context(cwd=manifest.path):
          self.m.git.push(manifest.url,
                          "%s:%s" % (manifest.gitiles_commit.id, ref))
