# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Utilities for testing cros_artifacts API."""

from recipe_engine import recipe_test_api


class CrosArtifactsTestApi(recipe_test_api.RecipeTestApi):
  """Fake data for cros_artifacts tests."""

  @property
  def bundle_response(self):
    """Returns a fake BundleResponse as a string."""
    artifact_path = str(self.m.path['start_dir'].join('tmp/artifact.tar.gz'))
    return """\
{
  "artifacts": [{"path": "%s"}]
}""" % artifact_path
