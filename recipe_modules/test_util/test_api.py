# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API to simplify testing CrOS recipes.

This module provides helpers to make testing CrOS recipes simpler and more
consistent.
"""

from collections import namedtuple

from google.protobuf.json_format import MessageToDict

from PB.chromiumos.common import BuildTarget
from PB.go.chromium.org.luci.buildbucket.proto.common import Trinary
from PB.recipe_modules.chromeos.build_menu.build_menu import BuildMenuProperties

from recipe_engine import recipe_test_api


class TestUtilApi(recipe_test_api.RecipeTestApi):
  """Helpers for testing CrOS Recipes."""

  def test_child_build(self, build_target_name, builder_name=None,
                       input_properties=None, **kwargs):
    """Return buildbucket step_data for a typical child builder.

    The build will be created with input properties that have
    build_target.name=|build_target_name|.  Defaults are always provided for
    bucket and, when build_target_name is given, builder.

    Args:
      build_target_name (str): Name of the build_target, or None for no
          build_target.
      builder_name (str): Name of the builder, or None to use {build_target-name}-{bucket}.
      input_properties (BuildMenuProperties or dict): input properties, or
          None.
      kwargs (dict): see test_build()

    Returns:
      An object with attributes:
        message: buildbucket.Build message.
        build: Step_data for the build.
    """
    input_dict = input_properties or {}
    if not isinstance(input_dict, dict):
      input_dict = MessageToDict(input_dict, preserving_proto_field_name=True)
    kwargs.setdefault('bucket', 'cq' if kwargs.get('cq') else 'postsubmit')
    if build_target_name:
      build_target = {'name': build_target_name}
      # We may already have build_menu properties.  Passing build_target_name
      # overrides the value in any input properties we received.
      input_dict.setdefault('$chromeos/build_menu', {})
      input_dict['$chromeos/build_menu']['build_target'] = build_target
      # TODO(crbug/1099259: build_target is moving to $chromeos/build_menu
      # properties.  Drop this when no longer needed.
      input_dict['build_target'] = build_target
      if not builder_name:
        suffix = '-snapshot' if kwargs[
            'bucket'] == 'postsubmit' else f'-{kwargs["bucket"]}'
        builder_name = f'{build_target_name}{suffix}'

      kwargs.setdefault('builder', builder_name)

    return self.test_build(input_properties=input_dict, **kwargs)

  def test_orchestrator(self, **kwargs):
    """Return buildbucket step_data for a typical orchestrator.

    Defaults are provided for bucket and builder.

    Args:
      kwargs (dict): see test_build()

    Returns:
      An object with attributes:
        message: buildbucket.Build message.
        build: Step_data for the build.
    """
    kwargs.setdefault('bucket', 'cq' if kwargs.get('cq') else 'postsubmit')
    kwargs.setdefault(
        'builder', 'snapshot-orchestrator' if kwargs['bucket'] == 'postsubmit'
        else '%s-orchestrator' % kwargs['bucket'])
    kwargs.setdefault('bot_size', 'small')
    return self.test_build(**kwargs)

  def test_build(self, cq=False, dry_run=False, bot_size='large',
                 extra_changes=None, exe=None, input_properties=None,
                 experiments=None, create_time=None, start_time=None,
                 update_time=None, end_time=None, critical=None,
                 output_properties=None, output_gitiles_commit=None, tags=None,
                 created_by=None, **kwargs):
    """Return a buildbucket step_data for a typical test build.

    In general, test_orchestrator() should be called for orchestrators, and
    test_child_build should be called for children of an orchestrator.

    This differs from the buildbucket/test_api.py ci_build() and try_build() in
    that we tweak things to reflect chromeos:
      - project defaults to 'chromeos'.
      - bucket defaults to 'cq' or 'postsubmit, depending on |cq|.
      - git_repo defaults to 'https://chromium.googlesource.com/project-a'.

    Args:
      cq (bool): whether this is a CQ triggered job, vs scheduled.  This also
          adds a default gerrit_change, and sets CQ properties.
      dry_run (bool): Whether this is a dry_run (used only when |cq|=True).
      bot_size (str): CrOS bot_size dimension for the builder.
      extra_changes (list[GerritChange]): additional changes to add.
      exe (common_pb2.Executable): Executable for the build.  (passed to
          buildbucket.build)
      input_properties: A protobuf input properties message, a dictionary of
          input properties, or None.  If used, the dictionary may be a superset
          of protobufs.
      experiments (list[str]): List of experiments to apply to the build.
      create_time (seconds): Create time, in seconds since epoch.
      start_time (seconds): Start time, in seconds since epoch.
      update_time (seconds): Update time, in seconds since epoch.
      end_time (seconds): End time, in seconds since epoch.
      critical (Trinary or str): Value (or name if str) to pass for critical.
      output_properties: A protobuf output properties message, a dictionary of
          output properties, or None.  If used, the dictionary may be a superset
          of protobufs.  If |output_properties| evaluates False, then the
          message and build will have NO output properties.  If specified, the
          output properties will be
          |input_properties|.update(|output_properties|).
      output_gitiles_commit (GitilesCommit): commit to set on the Output.
      tags: (list[StringPair] or key-value dict): tags to pass to the build.  If
          a dict is given, it will be passed as arguments to cros_tags.tags()
      **kwargs: see buildbucket/test_api.py

    Returns:
      An object with attributes:
        message: buildbucket.Build message.
        build: Step_data for the build.
    """
    _test_build_return = namedtuple('_test_build_return', ['message', 'build'])

    kwargs.setdefault('project', 'chromeos')
    kwargs.setdefault('on_backend', True)
    kwargs.setdefault('bucket', 'cq' if cq else 'postsubmit')
    kwargs.setdefault('git_repo', 'https://chromium.googlesource.com/project-a')

    tags = self.m.cros_tags.tags(**tags) if isinstance(tags, dict) else tags

    input_dict = input_properties or {}
    if not isinstance(input_dict, dict):
      input_dict = MessageToDict(input_dict, preserving_proto_field_name=True)

    output_dict = output_properties or {}
    if not isinstance(output_dict, dict):
      output_dict = MessageToDict(output_dict, preserving_proto_field_name=True)

    func = (
        self.m.buildbucket.try_build_message
        if cq else self.m.buildbucket.ci_build_message)

    msg = func(tags=tags, **kwargs)
    # If we were passed revision=None, clear the gitiles_commit.
    if not cq and 'revision' in kwargs and not kwargs['revision']:
      msg.input.gitiles_commit.Clear()
    msg.input.gerrit_changes.extend(extra_changes or [])
    if bot_size:
      msg = self.m.buildbucket.extend_swarming_bot_dimensions(
          msg, {'bot_size': bot_size})
    msg.created_by = created_by if created_by else msg.created_by

    if critical:
      msg.critical = (
          Trinary.Value(critical) if isinstance(critical, str) else critical)

    if create_time:
      msg.create_time.seconds = create_time
    if exe:
      msg.exe.cipd_package = exe.cipd_package
      msg.exe.cipd_version = exe.cipd_version
    msg.input.properties.update(input_dict)
    msg.input.experiments.extend(experiments)

    # These fields show up in buildbucket.build as the build progresses.  Let
    # the user add them for testing.
    if start_time:
      msg.start_time.seconds = start_time
    if update_time:
      msg.update_time.seconds = update_time
    if end_time:
      msg.end_time.seconds = end_time

    # If output_properties were not passed, then we do not set output_properties
    # in the message at all.  If they were, then we copy the input_properties,
    # and update with output_properties after that.
    if output_dict:
      msg.output.properties.update(input_dict)
      msg.output.properties.update(output_dict)

    if output_gitiles_commit:
      msg.output.gitiles_commit.CopyFrom(output_gitiles_commit)

    ret = self.m.buildbucket.build(msg)
    if input_dict:
      ret += self.m.properties(**input_dict)
    if cq:
      run_mode = self.m.cv.DRY_RUN if dry_run else self.m.cv.FULL_RUN
      ret += self.m.cv(run_mode=run_mode)

    return _test_build_return(msg, ret)

  def build_menu_properties(self, build_target_name=None, **kwargs):
    """Helper for updating input.properties in a Build message.

    Args:
      build_target_name (str): The name to use for the build_target, or None.
      kwargs (dict): Other key value pairs for BuildMenuProperties.
    Raises:
      ValueError if build_target_name and build_target are both set.

    Returns:
      (dict) Dictionary to pass to message.input.properties.update()
    """
    if build_target_name:
      if kwargs.get('build_target'):
        raise ValueError('Both build_target and build_target_name given.')
      kwargs['build_target'] = BuildTarget(name=build_target_name)
    return {
        '$chromeos/build_menu':
            MessageToDict(
                BuildMenuProperties(**kwargs), preserving_proto_field_name=True)
    }
