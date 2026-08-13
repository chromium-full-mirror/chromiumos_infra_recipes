# Copyright 2026 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Test API for the pupr_gerrit_interface module."""

from typing import Dict, List, Optional
from PB.go.chromium.org.luci.buildbucket.proto.common import GerritChange
from recipe_engine import recipe_test_api


class PuprGerritInterfaceTestApi(recipe_test_api.RecipeTestApi):
  """Helpers for testing the pupr_gerrit_interface module."""

  def set_gerrit_fetch_changes_response(
      self,
      parent_step_name: str,
      changes: List[GerritChange],
      values_dict: Optional[Dict[int, dict]] = None,
      owner_account_id: int = 100,
      uploader_account_id: int = 100,
      iteration: int = 1,
      step_name: Optional[str] = None,
  ) -> recipe_test_api.TestData:
    """Return simulated fetch_patch_sets response with default uploader and owner."""
    values_dict = values_dict or {}
    for change in changes:
      entry = values_dict.setdefault(change.change, {})
      if 'owner' not in entry:
        entry['owner'] = {'_account_id': owner_account_id}
      if 'uploader' not in entry:
        entry['uploader'] = {'_account_id': uploader_account_id}
    return self.m.gerrit.set_gerrit_fetch_changes_response(
        parent_step_name,
        changes,
        values_dict,
        iteration=iteration,
        step_name=step_name,
    )

  def set_retry_cl_response(
      self,
      parent_step_name: str,
      change_number: int,
      host: str = 'chromium-review.googlesource.com',
      patchset: int = 5,
      owner_account_id: int = 100,
      uploader_account_id: int = 100,
  ) -> recipe_test_api.TestData:
    """Return simulated fetch_patch_sets response for a retry_cl call."""
    changes = [GerritChange(host=host, change=change_number, patchset=patchset)]
    values_dict = {
        change_number: {
            'owner': {
                '_account_id': owner_account_id
            },
            'revision_info': {
                '_number': patchset,
                'uploader': {
                    '_account_id': uploader_account_id
                },
            },
        }
    }
    return self.m.gerrit.set_gerrit_fetch_changes_response(
        f'{parent_step_name}.retry CL {change_number}',
        changes,
        values_dict,
    )
