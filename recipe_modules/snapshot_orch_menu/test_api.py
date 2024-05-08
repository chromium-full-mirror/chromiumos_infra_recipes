# -*- coding: utf-8 -*-
# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API to simplify testing CrOS recipes.

This module provides helpers to make testing CrOS recipes simpler and more
consistent.
"""

from collections import namedtuple
import typing

from recipe_engine import recipe_test_api
from PB.go.chromium.org.luci.buildbucket.proto.build import Build
from PB.go.chromium.org.luci.buildbucket.proto.builds_service import (
    BatchResponse)
from PB.test_platform.taskstate import TaskState


class SnapshotOrchMenuTestApi(recipe_test_api.RecipeTestApi):
  """Helpers for testing CrOS Recipes."""

  def test(self, name, *args, **kwargs):  # pylint: disable=arguments-differ
    """A test, with orchestrator and OrchMenuProperties,

    This function creates a test orchestrator from kwargs, and then calls
    api.test() to create the TestData for a test.

    Default input properties are provided.

    Args:
      with_history (bool): Whether to set enable_history and assert_singleton in
        input_properties.
      with_manifest_refs (bool): Whether to add default update_manifest_refs to
        input_properties.
      git_footers (list): The list of git footers to return from build history,
        or None.  Only used if with_history evaluates True.
      history_builds (list): List of build messages to return when we are
        checking history, or None.
      collect_builds (list): List of build messages to return when we are
        collecting child builds, or None.
      collect_timeout (bool): Wheter the child builds time out.
      collect_after_builds (list): List of build messages to return when we are
        collect_aftering child builds, or None.
      process_child (Build): The Build message for a process child, or None.
      process_child_timeout (bool): Whether the process child times out.
      follow_on_orch (Build): The Build message for a follow-on orchestrator, or
        None.
      sheriff_rotations (list): List of sheriff rotations watching this orch.
      *args (list): Arguments to pass to test_api.test.
      **kwargs (dict): Arguments to pass to test_util.test_build.

    Returns:
      (recipe_test_api.TestData) TestData for the test.
    """
    # Because of *args and **kwargs, we need to fetch our arguments from kwargs.
    status = kwargs.pop('status', 'SUCCESS')
    with_history = kwargs.pop('with_history', False)
    with_manifest_refs = kwargs.pop('with_manifest_refs', False)
    max_build_failure_ratio = kwargs.pop('max_build_failure_ratio', 0.0)
    collect_builds = kwargs.pop('collect_builds', [])
    collect_timeout = kwargs.pop('collect_timeout', None)
    collect_after_builds = kwargs.pop('collect_after_builds', [])
    follow_on_orch = kwargs.pop('follow_on_orch', None)
    sheriff_rotations = kwargs.pop('sheriff_rotations', [])

    default_props = {
        '$chromeos/snapshot_orch_menu':
            self.get_default_module_properties(
                with_manifest_refs=with_manifest_refs,
                with_history=with_history,
                max_build_failure_ratio=max_build_failure_ratio)
    }
    # TODO(crbug/1098798): Stop using the recipe properties once they have moved
    # to module properties.  For now, copy the module properties into recipe
    # properties.
    for key in 'update_manifest_refs', 'enable_history', 'assert_singleton':
      if key in default_props['$chromeos/snapshot_orch_menu']:
        default_props[key] = default_props['$chromeos/snapshot_orch_menu'][key]
    kwargs.setdefault('input_properties', default_props)
    if with_history:
      kwargs['input_properties'].update(enable_history=True,
                                        assert_singleton=True)
    if sheriff_rotations:
      kwargs['input_properties'].update(sheriff_rotations=sheriff_rotations)

    ret = self.m.test_util.test_orchestrator(**kwargs).build
    args = list(args)

    if collect_builds:
      if collect_timeout:
        args.extend([
            self.step_data('run builds.collect.wait', retcode=1),
            self.m.buildbucket.simulated_get_multi(collect_builds,
                                                   'run builds.get')
        ])
      else:
        args.append(
            self.m.buildbucket.simulated_collect_output(collect_builds,
                                                        'run builds.collect'))

    child_builds = collect_builds + collect_after_builds
    if child_builds:
      ret += self.m.buildbucket.simulated_search_results(
          child_builds, 'clean up orchestrator.buildbucket.search')

    if follow_on_orch:
      args.append(
          self.m.buildbucket.simulated_schedule_output(
              BatchResponse(responses=[{
                  'schedule_build': follow_on_orch
              }]), 'run follow on orchestrator.buildbucket.schedule')
      )  # pragma: nocover
      args.append(
          self.m.buildbucket.simulated_collect_output(
              [follow_on_orch],
              'run follow on orchestrator.collect'))  # pragma: nocover

    # Call recipe_test_api.test().
    return super().test(name, ret, *args, status=status)

  def get_default_module_properties(self, with_manifest_refs=False,
                                    with_history=False,
                                    max_build_failure_ratio=0.0):
    """Return the default properties for the module."""
    ret = {'stagger_children_seconds': 10}
    if with_manifest_refs:
      ret['update_manifest_refs'] = {
          'build': 'refs/heads/green',
          'start': 'refs/heads/postsubmit',
          'max_build_failure_ratio': max_build_failure_ratio,
      }
    if with_history:
      ret.update(enable_history=True, assert_singleton=True)
    return ret

  def standard_test_data(self, extra_output_properties=None):
    """Return the standard test builds for testing orchestrators.

    Args:
      extra_output_properties (dict): Extra output properties, or None.

    Returns:
      namedtuple containing:
        orchestrator (Build): Build message for a running orchestrator.
        inflight_orchestrator (Build): Build message for an inflight
          orchestrator.
        builds (list): List of child builds for most tests.
        crit_fail (list): List of builds that includes a failed critical child.
        non_crit_fail (list): List of builds that includes a failed non-critical
          child.
        process_child (Build): Build message for a process-child.
        follow_on_orchestrator (Build): Build message for a follow-on
          orchestrator.
        ctp_normal (StepTestData): StepTestData for normal buildset.
        ctp_failure (StepTestData): StepTestData for build failing tests.
    """
    _ret = namedtuple('_standard_test_data', [
        'orchestrator', 'inflight_orchestrator', 'builds', 'history_builds',
        'after_builds', 'crit_fail', 'non_crit_fail', 'process_child',
        'follow_on_orchestrator', 'mixed_build_results', 'ctp_normal',
        'ctp_failure'
    ])

    def _child_build_msg(name, **kwargs):
      """Return the Build message for a child build."""
      kwargs.setdefault('status', 'SUCCESS')
      return self.m.test_util.test_child_build(name, **kwargs).message

    def _output_properties(extra=None):
      """Return output properties for the build."""
      props = {}
      props.update(extra or {})
      props.update(extra_output_properties or {})
      return props

    orchestrator = self.m.test_util.test_orchestrator(
        cq=True, build_id=8922054662172513000, status='STARTED').message

    inflight_orchestrator = self.m.test_util.test_orchestrator(
        cq=True, build_id=8922054662172513001, status='STARTED').message

    follow_on_orchestrator = self.m.test_util.test_orchestrator(
        build_id=8922054662172515000, bucket='toolchain',
        builder='artifact-verify-orchestrator', status='SUCCESS').message

    builds = [
        _child_build_msg(
            'amd64-generic', cq=True, build_id=8922054662172514000,
            critical='YES',
            output_properties=_output_properties({'build_cost': 10.0})),
        _child_build_msg('arm-generic', cq=True, build_id=8922054662172514001,
                         status='STARTED', critical='YES',
                         output_properties=_output_properties()),
        _child_build_msg('atlas', cq=True, build_id=8922054662172514002,
                         start_time=1562475245, revision=None, critical='YES',
                         output_properties=_output_properties()),
    ]
    history_builds = [b for b in builds if b.status == 'SUCCESS']
    collect_builds = [
        b for b in builds if b.status != 'SUCCESS' or b.start_time
    ]
    after_builds = [
        _child_build_msg('cave', cq=True, build_id=8922054662172514003,
                         start_time=1562475245, revision=None, critical='YES',
                         output_properties=_output_properties()),
    ]

    process_child = _child_build_msg('chell', build_id=8922054662172514501,
                                     status='SUCCESS', bucket='toolchain',
                                     builder='benchmark-afdo-process')

    crit_fail = [
        _child_build_msg('amd64-generic', build_id=8922054662172514000,
                         status='FAILURE', critical='YES'),
        _child_build_msg('amd64-generic', build_id=8922054662172514001,
                         critical='NO')
    ]
    non_crit_fail = [
        _child_build_msg('amd64-generic', build_id=8922054662172514000,
                         critical='YES'),
        _child_build_msg('arm-generic', build_id=8922054662172514001,
                         status='FAILURE', critical='NO')
    ]

    mixed_build_results = [
        _child_build_msg('amd64-generic', build_id=8922054662172514000,
                         status='FAILURE', critical='YES'),
        _child_build_msg('amd64-generic', build_id=8922054662172514001,
                         status='INFRA_FAILURE', critical='NO'),
        _child_build_msg('arm-generic', build_id=8922054662172514002,
                         status='SUCCESS', critical='YES'),
        _child_build_msg('arm-generic', build_id=8922054662172514003,
                         status='SUCCESS', critical='NO'),
    ]

    values = [
        orchestrator,
        inflight_orchestrator,
        collect_builds,
        history_builds,
        after_builds,
        crit_fail,
        non_crit_fail,
        process_child,
        follow_on_orchestrator,
        mixed_build_results,
    ]

    def _ctp_sched_resp(build_id):
      return BatchResponse(responses=[
          {
              'schedule_build':
                  self.m.test_util.test_build(
                      build_id=build_id, bucket='testplatform',
                      builder='cros_test_platform', bot_size=None,
                      status='SUCCESS').message
          },
      ])

    id1 = 1234
    id2 = 4321
    ctp_normal = self.m.buildbucket.simulated_schedule_output(
        _ctp_sched_resp(id1),
        'run tests.schedule tests.schedule hardware tests.'
        'schedule skylab tests v2.buildbucket.schedule')
    ctp_failure = self.m.buildbucket.simulated_schedule_output(
        _ctp_sched_resp(id1),
        'run tests.schedule tests.schedule hardware tests.'
        'schedule skylab tests v2.buildbucket.schedule')

    ctp_normal += self.m.buildbucket.simulated_schedule_output(
        _ctp_sched_resp(id2),
        'run tests.schedule tests.schedule hardware tests.'
        'schedule skylab tests v2.buildbucket.schedule')
    ctp_failure += self.m.buildbucket.simulated_schedule_output(
        _ctp_sched_resp(id2),
        'run tests.schedule tests.schedule hardware tests.'
        'schedule skylab tests v2.buildbucket.schedule')

    def _skylab_resp(task_id, suite_names=None, passed=True):
      verdict = TaskState.VERDICT_PASSED if passed else TaskState.VERDICT_FAILED
      return self.m.skylab_results.test_with_multi_response(
          bid=task_id, names=suite_names or [],
          task_state=TaskState(verdict=verdict))

    ctp_normal += self.m.buildbucket.simulated_collect_output([
        _skylab_resp(
            id2, suite_names=[
                'htarget.hw.bvt-cq',
                'htarget.hw.bvt-inline',
                'htarget.hw.some-suite',
                'htarget.hw.some-other-suite',
            ])
    ], 'run tests.collect tests.collect skylab tasks v2.buildbucket.collect')
    ctp_failure += self.m.buildbucket.simulated_collect_output([
        _skylab_resp(
            id2, suite_names=[
                'htarget.hw.bvt-cq',
                'htarget.hw.bvt-inline',
                'htarget.hw.some-suite',
                'htarget.hw.some-other-suite',
            ], passed=False)
    ], 'run tests.collect tests.collect skylab tasks v2.buildbucket.collect')

    values.extend([ctp_normal, ctp_failure])
    return _ret(*values)

  # TODO(b/279016710): This function could be generalized and allow overriding
  # of child build data.
  def orch_child_builds(
      self, orchestrator_name: str, child_builder_suffix: str
  ) -> typing.Tuple[typing.List[Build], typing.List[Build]]:
    """Return a list of child builds that the given orchestrator could run.

    Args:
      orchestrator_name: The name of the orchestrator for which to get child
          builds.
      child_builder_suffix: The suffix added to the build target to get the full
          child builder name (e.g. '-cq').

    Returns:
      Tuple containing:
        * List of Builds which have COLLECT or NO_COLLECT handling
        * List of Builds which have COLLECT_AFTER_HW_TEST handing
    """

    def _child_build_msg(build_target_name, **kwargs):
      """Return the Build message for a child build."""
      kwargs.setdefault('status', 'SUCCESS')
      return self.m.test_util.test_child_build(build_target_name,
                                               **kwargs).message

    orch_config = None
    for config in self.m.cros_infra_config.builder_configs_test_data.builder_configs:
      if config.id.name == orchestrator_name:
        orch_config = config
        break
    if not orch_config:
      return [], []  # pragma: no cover

    start_build_id = 8922054662172514000
    collect_builds = []
    collect_after_builds = []

    # TODO(b/279016710): Group NO_COLLECT builds with COLLECT for now. We will
    # need to update the orch_menu.test() function with a new option that adds
    # test_data for scheduling the NO_COLLECT builds but not collecting them.
    for c in orch_config.orchestrator.child_specs:
      target = c.name.split(child_builder_suffix)[0]
      collect_builds.append(
          _child_build_msg(target,
                           cq=orchestrator_name.endswith('cq-orchestrator'),
                           builder_name=c.name, build_id=start_build_id,
                           critical='YES',
                           output_properties={'build_cost': 10.0}))
      start_build_id += 1

    return collect_builds, collect_after_builds
