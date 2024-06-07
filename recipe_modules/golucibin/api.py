# -*- coding: utf-8 -*-
# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API to call into Go luci binaries."""

from typing import List
from recipe_engine import recipe_api

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2


class GoLuciBinAPI(recipe_api.RecipeApi):
  """Module for running Go luci binaries."""

  def __init__(self, *args, **kwargs):
    super().__init__(*args, **kwargs)

    self._cipd_package_base = 'chromiumos/infra/%s/${platform}'
    self._cipd_dirs = {}
    self._cipd_paths = {}

  def execute_luciexe(self, package: str, cipdLabel: str,
                      args: List[str] = None, runningAsync: bool = False):
    """Execute go luciexe binary."""
    if args is None:
      args = []
    self.ensure_package(package, cipdLabel)
    fullname = self._package_fullname(package, cipdLabel)

    build = build_pb2.Build()
    build.CopyFrom(self.m.buildbucket.build)

    for ofield in ['output', 'status', 'summary_markdown', 'steps']:
      build.ClearField(ofield)
    cmd = [self._cipd_paths[fullname], '--']
    for arg in args:  # pragma: no cover
      cmd.append(arg)
    stepName = '%s sub-build' % package
    if runningAsync:  # pragma: no cover
      stepName += ' (async)'

    with self.m.context():
      self.m.step.sub_build(stepName, cmd, build)

  def ensure_package(self, package: str, cipdLabel: str):
    fullname = self._package_fullname(package, cipdLabel)
    if fullname in self._cipd_paths:
      return

    with self.m.step.nest('ensure %s (%s)' % (package, cipdLabel)):
      with self.m.context(infra_steps=True):
        if cipdLabel not in self._cipd_dirs:
          self._cipd_dirs[
              cipdLabel] = self.m.path.start_dir / 'cipd' / cipdLabel
        pkgs = self.m.cipd.EnsureFile()
        pkgs.add_package(self._cipd_package_base % package, cipdLabel)
        self.m.cipd.ensure(self._cipd_dirs[cipdLabel], pkgs)

        self._cipd_paths[fullname] = self._cipd_dirs[cipdLabel] / package

  def _package_fullname(self, package: str, cipdLabel: str) -> str:
    return '%s-%s' % (package, cipdLabel)
