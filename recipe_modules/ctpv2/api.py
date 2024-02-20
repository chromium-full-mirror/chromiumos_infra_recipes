# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API to call into the CTPv2 binary"""

import copy
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
    self.allowed_pools = []

  def is_enabled(self):
    """Checks if ctpv2 is enabled for use.

        Returns: bool
        """
    return self._cipd_label is not None

  def execute_luciexe(self, use_legacy=False, runningAsync=False):
    """Execute work via ctpv2 luciexe binary."""
    self.ensure_ctpv2()
    build = build_pb2.Build()
    build.CopyFrom(self.m.buildbucket.build)
    if use_legacy:  # pragma: no cover
      build.input.properties['requests'] = self.filter_legacy_requests(
          build.input.properties['requests'])

    for ofield in ['output', 'status', 'summary_markdown', 'steps']:
      build.ClearField(ofield)
    cmd = self._cipd_dir.join('ctpv2')
    stepName = 'ctpv2 sub-build'
    if runningAsync:  # pragma: no cover
      stepName += ' (async)'

    with self.m.context(infra_steps=True):
      self.m.step.sub_build(stepName, [cmd], build)

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

  def set_allowed_pools(self, allowed_pools):  # pragma: no cover
    """Set the allowed ctp2 pools"""
    self.allowed_pools = allowed_pools

  def filter_legacy_requests(self, requests, reverse=False):  # pragma: no cover
    """Filter out the legacy requests based on allowed pools.

        Args:
          * requests: Dict of legacy v1 requests.
          * reverse: boolean to flip the filter result.

        Returns dict of filtered legacy v1 requests.
        """
    result = copy.deepcopy(requests)
    for name, request in requests.items():
      meets_criteria = False
      params = request.params if hasattr(request,
                                         'params') else request['params']
      decorations = params.decorations if hasattr(
          params, 'decorations') else params['decorations']
      if decorations:
        tags = decorations.tags if hasattr(decorations,
                                           'tags') else decorations['tags']
        for tag in tags:
          if tag.startswith('label-pool:'):
            tag = tag.lstrip('label-pool:')
          elif tag.startswith('pool:'):
            tag = tag.lstrip('pool:')
          else:
            continue
          if tag in self.allowed_pools:
            meets_criteria = True
      # XOR meets_criteria with reverse to
      # produce the reversing boolean algebra.
      if not meets_criteria ^ reverse:
        del result[name]

    return result
