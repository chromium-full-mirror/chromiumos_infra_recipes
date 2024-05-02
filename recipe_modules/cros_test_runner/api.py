# -*- coding: utf-8 -*-
# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Module for interacting with cros_test_runner."""

from recipe_engine import recipe_api

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2


class CrosTestRunnerCommand(recipe_api.RecipeApi):
  """Module for issuing cros_test_runner commands"""

  def __init__(self, properties, **kwargs):
    super().__init__(**kwargs)
    self._cipd_dir = None
    self._cipd_label = str(properties.version.cipd_label) or None
    self._cipd_package = str(properties.version.cipd_package) or \
        'chromiumos/infra/cros_test_runner/${platform}'

  def is_enabled(self):
    """Checks if cros_test_runner is enabled for use.

    Returns: bool
    """
    return self._cipd_label is not None

  def is_dynamic(self):
    """Checks if cros_test_runner contains the dynamic TRv2 request.

    Returns: bool
    """
    build = build_pb2.Build()
    build.CopyFrom(self.m.buildbucket.build)
    return 'cros_test_runner_dynamic_request' in build.input.properties

  def execute_luciexe(self):
    """Execute work via cros_test_runner luciexe binary."""
    self.ensure_cros_test_runner()
    build = build_pb2.Build()
    build.CopyFrom(self.m.buildbucket.build)
    for ofield in ['output', 'status', 'summary_markdown', 'steps']:
      build.ClearField(ofield)
    cmd = self._cipd_dir / 'cros_test_runner'

    with self.m.context():
      result = self.m.step.sub_build('cros_test_runner', [cmd], build,
                                     legacy_global_namespace=True,
                                     raise_on_failure=False)
      allowed_statuses = [self.m.step.SUCCESS, self.m.step.FAILURE]
      # pylint: disable=protected-access
      self.m.step._raise_on_disallowed_statuses(result, allowed_statuses)
      return result

  def ensure_cros_test_runner(self):
    """Ensure the cros_test_runner CLI is installed."""
    if self._cipd_dir:
      return

    with self.m.step.nest('ensure cros_test_runner'):
      with self.m.context(infra_steps=True):
        cipd_dir = self.m.path.start_dir / 'cipd' / 'cros_test_runner'

        pkgs = self.m.cipd.EnsureFile()
        pkgs.add_package(self._cipd_package, self._cipd_label)
        self.m.cipd.ensure(cipd_dir, pkgs)

        self._cipd_dir = cipd_dir

  def cipd_package_label(self):
    """Return the CTP CIPD package version (e.g. prod/staging/latest)."""
    return self._cipd_label
