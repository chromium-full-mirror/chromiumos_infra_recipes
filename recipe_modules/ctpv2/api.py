# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API to call into the CTPv2 binary."""

from recipe_engine import recipe_api
from google.protobuf.json_format import MessageToDict

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

  def get_ctpv2_with_fifo_list(self):  #pragma: nocover
    # Fetch the buildbucket build so that we can read the Ctpv2WithFifo list.
    build = build_pb2.Build()
    build.CopyFrom(self.m.buildbucket.build)
    props = MessageToDict(build.input.properties)

    # This only gets hit on a recipes test.
    if not props:
      props = {'$chromeos/migration': []}

    if '$chromeos/migration' not in props:  #pragma: nocover
      raise self.m.step.StepFailure(
          "migration list not provided in build input properties")

    props = props['$chromeos/migration']
    return props['ctpv2_with_fifo'] if 'ctpv2_with_fifo' in props else []


  def get_legacy_requests(self, requests, bucket='testplatform'):
    """return legacy requests.

    Args:
      requests: Map of legacy v1 requests.
      bucket: bucket of the current builder

    Returns:
      empty dict.
    """
    # return the unit test request for v1 to avoid recipes unit test failures until we get rid of recipes completely.
    # 100% of prod traffic should flow through ctpv2.
    return {
        name: request
        for name, request in requests.items()
        if self.pool_in_recipes_test_pool_list(request)
    }

  def get_v2_requests(self, requests, bucket='testplatform'):  #pragma: nocover
    """return v2 requests.

    Args:
      requests: Map of legacy v1 requests.
      bucket: bucket of the current builder

    Returns:
      dict of provided requests
    """
    # return the unit test request for v1 to avoid recipes unit test failures until we get rid of recipes completely.
    # 100% of traffic flows through ctpv2
    return {
        name: request
        for name, request in requests.items()
        if not self.pool_in_recipes_test_pool_list(request)
    }

  def runInCTPv2(self, request):  #pragma: nocover
    ctpv2WithFifo = self.get_ctpv2_with_fifo_list()

    params = self.get_val_from_obj_or_dict(request, 'params')
    if not params:  # pragma: no cover
      return False

    decorations = self.get_val_from_obj_or_dict(params, 'decorations')
    if not decorations:  # pragma: no cover
      return False

    tags = self.get_val_from_obj_or_dict(decorations, 'tags')

    if not tags:  # pragma: no cover
      raise self.m.step.StepFailure("request has no tags")

    for tag in tags:
      if tag.startswith('label-pool:'):
        tag = tag.removeprefix('label-pool:')
      elif tag.startswith('pool:'):
        tag = tag.removeprefix('pool:')
      else:
        continue

      # If the tag is going to the shared pool or the CTP W/ Fifo pools then
      # it is migrated to CTPv2.
      ctpv2WithFifo.extend(['DUT_POOL_QUOTA', 'MANAGED_POOL_QUOTA'])

      if tag in ctpv2WithFifo:
        return True
    return False

  def pool_in_recipes_test_pool_list(self, request):  #pragma: nocover
    ctpv1RecipesTestPools = [
        'recipesTest', 'schedukeRecipesTest', 'notSchedukeRecipesTest'
    ]

    params = self.get_val_from_obj_or_dict(request, 'params')
    if not params:  # pragma: no cover
      return False

    decorations = self.get_val_from_obj_or_dict(params, 'decorations')
    if not decorations:  # pragma: no cover
      return False

    tags = self.get_val_from_obj_or_dict(decorations, 'tags')

    if not tags:  # pragma: no cover
      raise self.m.step.StepFailure("request has no tags")

    for tag in tags:
      if tag.startswith('label-pool:'):
        tag = tag.removeprefix('label-pool:')
      elif tag.startswith('pool:'):
        tag = tag.removeprefix('pool:')
      else:
        continue

      if tag in ctpv1RecipesTestPools:
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
