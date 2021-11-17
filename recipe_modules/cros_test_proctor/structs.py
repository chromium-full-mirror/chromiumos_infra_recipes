# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Define Proctor structs."""

from collections import namedtuple

# Describes a MetaTestTuple.
# Fields:
#   skylab: A list of SkylabTasks or SkylabResults.
#   autotest_vm: A list of autotest_vm build_pb2.Build objects.
#   tast_vm: A list of tast_vm build_pb2.Build objects.
#   tast_gce: A list of tast_gce build_pb2.Build objects.
#   moblab_vm: A list of moblab_vm build_pb2.Build objects.
MetaTestTuple = namedtuple('MetaTestTuple',
                           ['skylab', 'autotest_vm', 'tast_vm', 'tast_gce'])
