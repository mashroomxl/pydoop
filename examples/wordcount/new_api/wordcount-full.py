#!/bin/bash

""":"
export HADOOP_HOME=$HADOOP_PREFIX
export PYTHON_EGG_CACHE=/tmp/python_cache
exec /usr/bin/python -u $0 $@
":"""

import sys
import logging

fh=logging.FileHandler("/tmp/testing.log")
fh.setLevel(logging.DEBUG)

logger = logging.getLogger("WordCount")
logger.addHandler(fh)

logger.warning("WTH")

import struct

import itertools as it
import pydoop.mapreduce.api as api
import pydoop.mapreduce.pipes as pp


from pydoop.utils.misc import jc_configure, jc_configure_int
import pydoop.hdfs as hdfs


WORDCOUNT = "WORDCOUNT"
INPUT_WORDS = "INPUT_WORDS"
OUTPUT_WORDS = "OUTPUT_WORDS"


class Mapper(api.Mapper):
    def __init__(self, context):
        super(Mapper, self).__init__(context)
        sys.stderr.write("Mapper initialized")
        self.logger = logger.getChild("Mapper")
        context.set_status("initializing")
        self.input_words = context.get_counter(WORDCOUNT, INPUT_WORDS)

    def map(self, context):
        k = context.key
        sys.stderr.write("Map: %r,%r" % (context.key, context.value))
        #self.logger.debug("key = %r" % struct.unpack(">q", k)[0])
        words = context.value.split()
        for w in words:
            context.emit(w, 1)

        context.increment_counter(self.input_words, len(words))


class Reducer(api.Reducer):
    def __init__(self, context):
        super(Reducer, self).__init__(context)
        sys.stderr.write("Ruducer initialized")
        self.logger = logger.getChild("Reducer")
        context.set_status("initializing")
        self.output_words = context.get_counter(WORDCOUNT, OUTPUT_WORDS)

    def reduce(self, context):
        sys.stderr.write("Reducer: %s" % context.key)
        s = 0
        for value in context.values:
            s += 1
        context.emit(context.key, str(s))
        context.increment_counter(self.output_words, 1)



class Reader(api.RecordReader):
    """
    Mimics Hadoop's default LineRecordReader (keys are byte offsets with
    respect to the whole file; values are text lines).
    """

    def __init__(self, context):
        self.logger = logger.getChild("Reader")
        sys.stderr.write("Reader.....")
        self.isplit = context.input_split
        for a in "filename", "offset", "length":
            #self.logger.debug("isplit.%s = %r" % (a, getattr(self.isplit, a)))
            sys.stderr.write("isplit.%r = %r" % (a, getattr(self.isplit, a)))
        self.file = hdfs.open(self.isplit.filename)
        #self.logger.debug("readline chunk size = %r" % self.file.chunk_size)
        sys.stderr.write("readline chunk size = %r" % self.file.chunk_size)
        self.file.seek(self.isplit.offset)
        self.bytes_read = 0
        if self.isplit.offset > 0:
            discarded = self.file.readline()  # read by reader of previous split
            self.bytes_read += len(discarded)

    def close(self):
        self.logger.debug("closing open handles")
        self.file.close()
        self.file.fs.close()

    def next(self):
        sys.stderr.write("next")
        if self.bytes_read > self.isplit.length:  # end of input split
            raise StopIteration
        key = struct.pack(">q", self.isplit.offset + self.bytes_read)  #FIXME: to be updated to the new serialize routine
        record = self.file.readline()
        if record == "":  # end of file
            raise StopIteration
        self.bytes_read += len(record)
        return (key, record)

    def get_progress(self):
        return min(float(self.bytes_read) / self.isplit.length, 1.0)


class Writer(api.RecordWriter):

    def __init__(self, context):
        super(Writer, self).__init__(context)
        self.logger = logging.getLogger("Writer")
        jc = context.getJobConf()
        jc_configure_int(self, jc, "mapred.task.partition", "part")
        jc_configure(self, jc, "mapred.work.output.dir", "outdir")
        jc_configure(self, jc, "mapred.textoutputformat.separator", "sep", "\t")
        jc_configure(self, jc, "pydoop.hdfs.user", "hdfs_user", None)
        self.outfn = "%s/part-%05d" % (self.outdir, self.part)
        self.file = hdfs.open(self.outfn, "w", user=self.hdfs_user)

    def close(self):
        self.logger.debug("closing open handles")
        self.file.close()
        self.file.fs.close()

    def emit(self, key, value):
        self.file.write("%s%s%s\n" % (key, self.sep, value))


class Partitioner(api.Partitioner):
    def __init__(self, context):
        super(Partitioner, self).__init__(context)
        self.logger = logging.getLogger("Partitioner")

    def partition(self, key, numOfReduces):
        reducer_id = (hash(key) & sys.maxint) % numOfReduces
        self.logger.debug("reducer_id: %r" % reducer_id)
        return reducer_id


if __name__ == "__main__":
    pp.run_task(pp.Factory(
        mapper_class=Mapper, reducer_class=Reducer,
        record_reader_class=Reader,
        record_writer_class=Writer,
        partitioner_class=Partitioner,
        combiner_class=Reducer
    ))

