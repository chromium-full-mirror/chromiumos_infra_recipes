# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_api

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2


class Ctpv2Command(recipe_api.RecipeApi):
  """Module for issuing ctpv2 commands"""

  def __init__(self, properties, **kwargs):
    super().__init__(**kwargs)
    self._cipd_dir = None
    self._cipd_label = str(properties.version.cipd_label) or None
    self._cipd_package = str(properties.version.cipd_package) or \
        'chromiumos/infra/ctpv2/${platform}'

  def is_enabled(self):
    """Checks if ctpv2 is enabled for use.

    Returns: bool
    """
    return self._cipd_label is not None

  def execute_luciexe(self):
    """Execute work via ctpv2 luciexe binary."""
    self.ensure_ctpv2()
    build = build_pb2.Build()
    build.CopyFrom(self.m.buildbucket.build)
    for ofield in ['output', 'status', 'summary_markdown', 'steps']:
      build.ClearField(ofield)
    cmd = self._cipd_dir.join('ctpv2')

    with self.m.context(infra_steps=True):
      self.m.step.sub_build('ctpv2', [cmd], build, legacy_global_namespace=True)

  def ensure_ctpv2(self):
    """Ensure the ctpv2 CLI is installed."""
    if self._cipd_dir:
      return

    with self.m.step.nest('ensure ctpv2'):
      with self.m.context(infra_steps=True):
        cipd_dir = self.m.path['start_dir'].join('cipd', 'ctpv2')

        pkgs = self.m.cipd.EnsureFile()
        pkgs.add_package(self._cipd_package, self._cipd_label)
        self.m.cipd.ensure(cipd_dir, pkgs)

        self._cipd_dir = cipd_dir

  def cipd_package_label(self):
    """Return the CTPv2 CIPD package version (e.g. prod/staging/latest)."""
    return self._cipd_label
