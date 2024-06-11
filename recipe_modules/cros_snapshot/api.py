# -*- coding: utf-8 -*-
# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API for working with CrOS snapshot builds."""

from typing import Optional

from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_api import StepFailure

from PB.chromiumos.builder_config import BuilderConfig
from PB.recipe_modules.chromeos.cros_snapshot.cros_snapshot import CrosSnapshotProperties


class CrosSnapshotApi(RecipeApi):
  """A module for steps that manipulates CrOS snapshot information."""

  def __init__(self, properties: CrosSnapshotProperties, *args, **kwargs):
    super().__init__(*args, **kwargs)
    self._properties = properties
    self._snapshot_identifier = str(properties.snapshot_identifier)

  def _read_workspace_snapshot_identifier(self, test_data=None):
    """Read the CrOS snapshot identifier from the workspace.

    Args:
      test_data: test data to use for the git_footers step.

    Returns: a snapshot identifier read from the workspace.
    """
    with self.m.step.nest('read snapshot identifier') as presentation:
      with self.m.context(cwd=self.m.src_state.build_manifest.path):
        snapshot_identifier_footers = self.m.git_footers.from_ref(
            self.m.src_state.gitiles_commit.id, key='Cr-Snapshot-Identifier',
            step_test_data=test_data)
        if not snapshot_identifier_footers:
          return ''

        if len(snapshot_identifier_footers) > 1:
          raise StepFailure('found more than one snapshot identifier')

        snapshot_identifier = str(snapshot_identifier_footers[0])
        presentation.step_text = 'found snapshot_identifier: %s' % snapshot_identifier
        return snapshot_identifier

  def snapshot_identifier(self, test_value: Optional[str] = None):
    """The snapshot identifier of the workspace checkout.

    Args:
      test_value: test value of the snapshot identifier.
    """
    test_data = None
    if test_value is not None:
      test_data = self.m.git_footers.test_api.step_test_data_factory(test_value)
    snapshot_identifier = self._read_workspace_snapshot_identifier(test_data)
    return self._snapshot_identifier or snapshot_identifier

  def is_snapshot_build(self) -> bool:
    """Return True if this build is a snapshot build running on a snapshot builder."""
    config = self.m.cros_infra_config.config
    if not config:  # pragma: no cover
      raise StepFailure('Missing builder config')
    if config.id.type == BuilderConfig.Id.Type.SNAPSHOT:
      return True

    # Doing an additional check, since some of snapshot builders have
    # POSTSUBMIT type.
    return bool(self._snapshot_identifier)
