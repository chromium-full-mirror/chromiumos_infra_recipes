# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.


from recipe_engine import recipe_api

from google.protobuf import text_format

from PB.chromiumos.test.plan import source_test_plan as source_test_plan_pb2


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

  def relevant_plans(self, gerrit_changes):
    """Call test_plan relevant-plans.

    Args:
      * gerrit_changes (list[common_pb2.GerritChange]): Changes to test, must be
          non-empty.

    Returns:
      A list of relevant SourceTestPlans
    """
    with self.m.step.nest('find relevant plans'), \
       self.m.context(infra_steps=True):
      self._ensure_test_plan()

      cmd = [
          self._test_plan_path,
          'relevant-plans',
          '-loglevel',
          'debug',
      ]

      for gc in gerrit_changes:
        cmd += ['-cl', self.m.gerrit.parse_gerrit_change_url(gc)]

      messages_path = self.m.path.mkdtemp(prefix='test_plan')
      output = messages_path.join("output.jsonproto")

      cmd += ['-output', output]

      self.m.step('call test_plan', cmd)

      # Output contains relevant plans in separate textproto files.
      output_files = self.m.file.listdir(
          'list output files',
          output,
          test_data=['relevant_plan_1.textpb', 'relevant_plan_2.textpb'],
      )
      relevant_plans = []

      for f in output_files:
        output_raw = self.m.file.read_raw('read output {}'.format(f), f)

        plan = source_test_plan_pb2.SourceTestPlan()
        text_format.Parse(output_raw, plan, allow_unknown_field=True)
        relevant_plans.append(plan)

      return relevant_plans

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
