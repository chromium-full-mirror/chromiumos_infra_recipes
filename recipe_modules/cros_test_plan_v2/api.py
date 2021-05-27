# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from google.protobuf import json_format

from recipe_engine import recipe_api

from PB.chromiumos.test.api import coverage_rule as coverage_rule_pb2


class CrosTestPlanV2Api(recipe_api.RecipeApi):
  """A module for generating and parsing test plans for CTP v2."""

  def __init__(self, properties, *args, **kwargs):
    super(CrosTestPlanV2Api, self).__init__(*args, **kwargs)
    self._properties = properties

  def initialize(self):
    self._cipd_package = (
        self._properties.test_plan_cipd_package.encode('utf-8') or
        "chromiumos/infra/test_plan/${platform}")

    default_ref = "staging" if self.m.cros_infra_config.is_staging else "prod"
    self._cipd_ref = (
        self._properties.test_plan_cipd_ref.encode('utf-8') or default_ref)

  def generate(self, gerrit_changes):
    """Call test_plan generate.

    Args:
      * gerrit_changes (list[common_pb2.GerritChange]): Changes to test, must be
          non-empty.

    Returns:
      Generated CoverageRules
    """
    with self.m.step.nest('generate test plan v2'), \
       self.m.context(infra_steps=True):
      self._ensure_test_plan()

      cmd = [
          self._test_plan_path,
          'generate',
          '-loglevel',
          'debug',
      ]

      for gc in gerrit_changes:
        cmd += ['-cl', self.m.gerrit.parse_gerrit_change_url(gc)]

      messages_path = self.m.path.mkdtemp(prefix='test_plan')
      output = messages_path.join("output.jsonproto")

      cmd += ['-output', output]

      self.m.step('call test_plan', cmd)

      # Output is newline-delimited jsonpb CoverageRules.
      output_raw = self.m.file.read_raw(
          'read output', output, test_data='\n'.join([
              json_format.MessageToJson(m).replace('\n', ' ') for m in [
                  self.test_api.kernel_coverage_rule(),
                  self.test_api.fp_coverage_rule(),
              ]
          ]))

      coverage_rules = []
      for json in output_raw.split('\n'):
        rule = coverage_rule_pb2.CoverageRule()
        json_format.Parse(json, rule, ignore_unknown_fields=True)
        coverage_rules.append(rule)

      return coverage_rules

  def _ensure_test_plan(self):
    """Ensure the test_plan cli is installed.

    Source code for test_plan is under
    https://source.corp.google.com/chromium_infra/go/src/infra/cros/cmd/test_plan/.
    """
    with self.m.step.nest('ensure test_plan'):
      with self.m.context(infra_steps=True):
        cipd_dir = self.m.path['start_dir'].join('cipd')

        pkgs = self.m.cipd.EnsureFile()
        pkgs.add_package(self._cipd_package, self._cipd_ref)
        self.m.cipd.ensure(cipd_dir, pkgs)

        self._test_plan_path = cipd_dir.join('test_plan')
