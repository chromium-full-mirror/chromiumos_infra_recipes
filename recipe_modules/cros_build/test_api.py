# Copyright 2019 The LUCI Authors. All rights reserved.
# Use of this source code is governed under the Apache License, Version 2.0
# that can be found in the LICENSE file.

from google.protobuf import struct_pb2
from google.protobuf import timestamp_pb2

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2

from recipe_engine import recipe_test_api

# IMPORTANT: This number is not arbitrary.
# The buildbucket module depends on this magic number in test mode.
# https://chromium.googlesource.com/infra/luci/recipes-py.git/+/master/recipe_modules/buildbucket/api.py#74
BASE_BUILD_ID = 8922054662172514000


class CrosBuildTestApi(recipe_test_api.RecipeTestApi):
  """Test examples for cros_build api."""

  def build_message(
      self,
      project='project',
      bucket='bucket',  # shortname.
      builder='builder',
      git_repo=None,
      git_ref='refs/heads/master',
      revision='2d72510e447ab60a9728aeea2362d8be2cbd7789',
      build_number=0,
      build_id=8945511751514863184,
      tags=None,
      status=None,
      build_target=None,
      input_properties=None,
      output_properties=None,
  ):
    """Returns a typical buildbucket CI build scheduled by luci-scheduler."""
    build = build_pb2.Build(
        id=build_id, number=build_number, tags=tags or [],
        builder=build_pb2.BuilderID(
            project=project,
            bucket=bucket,
            builder=builder,
        ), created_by='user:luci-scheduler@appspot.gserviceaccount.com',
        create_time=timestamp_pb2.Timestamp(seconds=1527292217),
        input=build_pb2.Build.Input(
            properties=struct_pb2.Struct().get_or_create_struct('output_props'),
            gitiles_commit=common_pb2.GitilesCommit(
                host="host",
                project="project",
                ref=git_ref,
                id=revision,
            ),
        ), output=build_pb2.Build.Output(
            properties=struct_pb2.Struct().get_or_create_struct('output_props'),
        ))

    if status:
      build.status = common_pb2.Status.Value(status)

    if input_properties:
      build.input.properties.update(input_properties)

    if build_target:
      build.input.properties['build_target'] = {'name': build_target}

    if output_properties:
      build.output.properties.update(output_properties)

    return build

  def example(self, builder, input_properties, build_target=None, status='SUCCESS'):
    if not hasattr(self, '_build_id'):
      self._build_id = BASE_BUILD_ID

    build_id = self._build_id
    self._build_id += 1

    return self.build_message(
        builder=builder, build_id=build_id, status=status,
        build_target=build_target,
        input_properties=input_properties,
        output_properties=dict(build_report_hash='DEADBEEF'))

  def simulated_collect_output(self, builds, step_name='collect'):
    return self.m.buildbucket.simulated_collect_output(builds,
                                                       step_name=step_name)

  def fail_download_report(self, build, step_name='download'):
    """Simulates build report download failure.

    Args:
      * build (build_pb2.Build): Build to simulate download failure.
    """
    return self.step_data('%s.%s' % (step_name, build.builder.builder),
                          retcode=1)
