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
      build.input.properties['requests'] = self.get_v2_requests(
          build.input.properties['requests'],
          self.m.buildbucket.build.builder.bucket)

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

  def get_legacy_requests(self, requests, bucket='testplatform'):
    """return legacy requests.

    Args:
      requests: Map of legacy v1 requests.
      bucket: bucket of the current builder

    Returns:
      Dict of legacy v1 requests that meet ctpv2 criteria (unless reversed).
    """
    bucket = bucket if bucket != '' else 'testplatform'
    bucket = bucket.removesuffix('.shadow')

    # If external is in the name then it is a partner bucket and all currently
    # are running in v1.
    if 'external' in bucket:  #pragma: nocover
      return dict(requests.items())

    if 'public' in bucket:  #pragma: nocover
      # The public builder still services mixed request so we want to maintain
      # the current filter.
      return {
          name: request
          for name, request in requests.items()
          if not self._meets_ctpv2_criteria(request)
      }

      # The standard CTP builder does not service any more v1 request. Force all
      # to be read as CTPv2 requests.
      #
      # This will also capture any new buckets which are not partners nor public
      # and force them into using CTPv2. This is by design as we no longer
      # intend to onboard new workflows onto the v1 stack.
    return {}

  def get_v2_requests(self, requests, bucket='testplatform'):  #pragma: nocover
    """return v2 requests.

    Args:
      requests: Map of legacy v1 requests.
      bucket: bucket of the current builder

    Returns:
      Dict of legacy v1 requests that meet ctpv2 criteria.
    """
    bucket = bucket if bucket != '' else 'testplatform'
    bucket = bucket.removesuffix('.shadow')

    if bucket == 'testplatform':
      # The standard CTP builder does not service any more v1 request. Force all
      # to be read as CTPv2 requests.
      #
      # This will also capture any new buckets which are not partners nor public
      # and force them into using CTPv2. This is by design as we no longer
      # intend to onboard new workflows onto the v1 stack.
      return dict(requests.items())
    if 'public' in bucket:
      # The public builder still services mixed request so we want to maintain
      # the current filter.
      return {
          name: request
          for name, request in requests.items()
          if self._meets_ctpv2_criteria(request)
      }

    return {}

  def _meets_ctpv2_criteria(self, request):  #pragma: nocover
    params = self.get_val_from_obj_or_dict(request, 'params')
    if not params:  # pragma: no cover
      return False
    if self._is_ctpv2_with_qs_request(params):
      return True
    return self._is_allowed_pool(params)

  def _has_ctpv2_allowed_prefix(self, params):  # pragma: no cover
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
    """Marks requests for CTPv2 execution with QS if (1) pool is outside allowed pool
    list and has AL. prefix


    Args:
        requests: A dictionary of legacy V1 requests.

    Returns:
        A dictionary/Struct of legacy V1 requests, with the `runCtpv2WithQs`
        field set to True
    """
    for request in requests.values():  # pragma: no cover
      params = self.get_val_from_obj_or_dict(request, 'params')
      if self._has_ctpv2_allowed_prefix(
          params) and not self._is_allowed_pool(params):
        _set_run_ctpv2_with_qs_param(params)


  def _is_ctpv2_with_qs_request(self, params):  #pragma: nocover
    run_via_cft = self.get_val_from_obj_or_dict(params, 'run_via_cft',
                                                'runViaCft')
    run_ctpv2_with_qs = self.get_val_from_obj_or_dict(params,
                                                      'run_ctpv2_with_qs',
                                                      'runCtpv2WithQs')
    return run_via_cft and run_ctpv2_with_qs

  def _is_allowed_pool(self, params):  #pragma: nocover
    in_main_pool = params is not None and self._is_main_pool_request(params)
    if in_main_pool:  # pragma: no cover
      return True
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

  @staticmethod
  def get_val_from_obj_or_dict(obj_or_dict, field,
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
