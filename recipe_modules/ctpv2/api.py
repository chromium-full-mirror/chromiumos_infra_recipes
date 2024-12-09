# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API to call into the CTPv2 binary."""

from recipe_engine import recipe_api
from google.protobuf.struct_pb2 import Struct

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2


class Ctpv2Command(recipe_api.RecipeApi):
  """Module for issuing ctpv2 commands."""

  def __init__(self, properties, **kwargs):
    super().__init__(**kwargs)
    self._cipd_dir = None
    self._cipd_label = str(properties.version.cipd_label) or None
    self._cipd_package = str(properties.version.cipd_package) or \
        'chromiumos/infra/ctpv2/${platform}'
    self.allowed_pools = []
    self._prefixed_tags_to_check = ['label-suite:', 'suite:', 'analytics_name:']

  def is_enabled(self) -> bool:
    """Check if ctpv2 is enabled for use."""
    return self._cipd_label is not None

  def execute_luciexe(self, req=None, tryCount=1):
    """Execute work via ctpv2 luciexe binary."""
    del tryCount
    if req is None:
      req = {}
    use_legacy = req.get('useLegacy', False)
    runningAsync = req.get('runningAsync', False)
    self.ensure_ctpv2()
    build = build_pb2.Build()
    build.CopyFrom(self.m.buildbucket.build)
    if use_legacy and 'requests' in build.input.properties:  # pragma: no cover
      self.mark_requests_for_ctpv2_with_qs(build.input.properties['requests'])
      build.input.properties['requests'] = self.filter_legacy_requests(
          build.input.properties['requests'])

    for ofield in ['output', 'status', 'summary_markdown', 'steps']:
      build.ClearField(ofield)
    cmd = self._cipd_dir / 'ctpv2'
    stepName = 'ctpv2 sub-build'
    if runningAsync:  # pragma: no cover
      stepName += ' (async)'

    return self.m.step.sub_build(
        stepName, [cmd], build,
        merge_output_properties_to=self.m.step.RootOutputProperties)

  def ensure_ctpv2(self):
    """Ensure the ctpv2 CLI is installed."""
    if self._cipd_dir:
      return

    with self.m.step.nest('ensure ctpv2'):
      with self.m.context(infra_steps=True):
        cipd_dir = self.m.path.start_dir / 'cipd' / 'ctpv2'

        pkgs = self.m.cipd.EnsureFile()
        pkgs.add_package(self._cipd_package, self._cipd_label)
        self.m.cipd.ensure(cipd_dir, pkgs)

        self._cipd_dir = cipd_dir

  def cipd_package_label(self):
    """Return the CTPv2 CIPD package version (e.g. prod/staging/latest)."""
    return self._cipd_label

  def set_allowed_pools(self, allowed_pools):  # pragma: no cover
    """Set the allowed ctp2 pools."""
    self.allowed_pools = allowed_pools

  def filter_legacy_requests(self, requests, reverse: bool = False):
    """Filter out the legacy requests based on allowed pools.

    Args:
      requests: Map of legacy v1 requests.
      reverse: If true, flip the filter result.

    Returns:
      Dict of legacy v1 requests that meet ctpv2 criteria (unless reversed).
    """
    return {
        name: request
        for name, request in requests.items()
        # XOR with reverse inverts the result.
        if self._meets_ctpv2_criteria(request) ^ reverse
    }

  def _meets_ctpv2_criteria(self, request):
    params = self.get_val_from_obj_or_dict(request, 'params')
    if not params:  # pragma: no cover
      return False
    if self._is_ctpv2_with_qs_request(params) \
      or self._has_ctpv2_allowed_prefix(params):
      return True
    return self._is_allowed_pool(params)

  def _has_ctpv2_allowed_prefix(self, params):
    decorations = self.get_val_from_obj_or_dict(params, 'decorations')
    if not decorations:  # pragma: no cover
      return False
    tags = self.get_val_from_obj_or_dict(decorations, 'tags')
    if not tags:  # pragma: no cover
      return False
    for tag in tags:
      for tag_to_check in self._prefixed_tags_to_check:
        if tag.startswith(tag_to_check):  # pragma: no cover
          tag = tag.removeprefix(tag_to_check)
          if tag.startswith('AL.'):
            return True
    return False

  def mark_requests_for_ctpv2_with_qs(self, requests):
    """Marks requests for CTPv2 execution with QS if (1) the CTPv2 with QS
    experiment is enabled and the request is intended for the main pool, or (2)
    the request has a CTPv2-allowed prefix but is not intended for the Scheduke
    pools allowlist.

    Args:
        requests: A dictionary of legacy V1 requests.

    Returns:
        A dictionary/Struct of legacy V1 requests, with the `runCtpv2WithQs`
        field set to True for requests that meet either (1) the criteria of
        being targeted for the main pool and part of the enabled experiment, or
        (2) having a CTPv2-allowed prefix but not being in the Scheduke pools
        allowlist
    """
    for request in requests.values():  # pragma: no cover
      params = self.get_val_from_obj_or_dict(request, 'params')
      ctp2_exp_enabled = 'chromeos.cros_infra_config.ctpv2_main_pool' in self.m.cros_infra_config.experiments
      in_main_pool = params is not None and self._is_main_pool_request(params)
      ctpv2_outside_of_pool_allowlist = (
          self._has_ctpv2_allowed_prefix(params) and
          not self._is_allowed_pool(params))
      if (not self._is_allowed_pool(params) and in_main_pool and
          ctp2_exp_enabled) or ctpv2_outside_of_pool_allowlist:
        _set_run_ctpv2_with_qs_param(params)

  def _is_main_pool_request(self, params):  # pragma: no cover
    # get scheduling info from params
    scheduling = self.get_val_from_obj_or_dict(params, 'scheduling')
    if scheduling is not None:
      # get managed_pool info from scheduling object
      managed_pool = self.get_val_from_obj_or_dict(scheduling, 'managed_pool',
                                                   'managedPool')

      # get unmanaged_pool info from scheduling object
      unmanaged_pool = self.get_val_from_obj_or_dict(scheduling,
                                                     'unmanaged_pool',
                                                     'unmanagedPool')

      # Check if the managed pool is one of the expected values
      if managed_pool is not None:
        if isinstance(managed_pool,
                      str) and managed_pool == 'MANAGED_POOL_QUOTA':
          return True
        if isinstance(managed_pool, int) and managed_pool == 8:  #enum int value
          return True

      if unmanaged_pool is not None:
        if isinstance(unmanaged_pool,
                      str) and unmanaged_pool in ('DUT_POOL_QUOTA', 'quota'):
          return True

    return False

  def _is_ctpv2_with_qs_request(self, params):
    run_via_cft = self.get_val_from_obj_or_dict(params, 'run_via_cft',
                                                'runViaCft')
    run_ctpv2_with_qs = self.get_val_from_obj_or_dict(params,
                                                      'run_ctpv2_with_qs',
                                                      'runCtpv2WithQs')
    return run_via_cft and run_ctpv2_with_qs

  def _is_allowed_pool(self, params):
    decorations = self.get_val_from_obj_or_dict(params, 'decorations')
    if not decorations:  # pragma: no cover
      return False
    tags = self.get_val_from_obj_or_dict(decorations, 'tags')
    if not tags:  # pragma: no cover
      return False
    for tag in tags:
      if tag.startswith('label-pool:'):
        tag = tag.removeprefix('label-pool:')
      elif tag.startswith('pool:'):
        tag = tag.removeprefix('pool:')
      else:
        continue
      if tag in self.allowed_pools:
        return True
    return False

  def get_val_from_obj_or_dict(self, obj_or_dict, field,
                               key=None):  # pragma: no cover
    """Retrieve the value from the obj/dict using the field/key.

    This is needed because filter legacy requests is called with both a proto
    object and a proto dict.
    """
    if hasattr(obj_or_dict, field):
      return getattr(obj_or_dict, field)
    key = key if key else field
    if key in obj_or_dict:
      return obj_or_dict[key]
    return None


def _set_run_ctpv2_with_qs_param(params):  # pragma: no cover
  # If params is a dict
  if isinstance(params, dict):
    params['runCtpv2WithQs'] = True
  # If params is a protobuf Struct
  elif isinstance(params, Struct):
    params.fields['runCtpv2WithQs'].bool_value = True
  # If params is another type of object
  else:
    setattr(params, 'run_ctpv2_with_qs', True)
