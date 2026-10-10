// Original port-level scoreboard for the actual generated P36 ApeRename.
// Restricted profile: architectural x10, up to four live speculative writers,
// out-of-order writeback, ordered commit, full recovery and relaunch clear.
// Checkpoint-selective recovery has a separate harness; no hierarchy peeking.
module RenameLifecycleFormal(input wire clk);
  (* anyseq *) reg reset, clear, recover, allocate, complete, commit;
  (* anyseq *) reg [1:0] completion_index;
  (* anyseq *) reg completion_value;
  reg [1:0] head = 0, tail = 0;
  reg [2:0] count = 0;
  reg [3:0] live = 0, written = 0, values = 0;
  reg [5:0] tags [0:3];
  reg [5:0] committed_tag = 10;
  reg committed_value = 0;
  wire allocate_ready;
  wire [5:0] allocated, source_tag, source_zero, free_count;
  wire [1:0] source_ready;
  wire [63:0] source_value, zero_value, argument;
  wire allocation = allocate && allocate_ready;
  wire [1:0] youngest = tail - 1'b1;
  wire [5:0] expected_tag = count != 0 ? tags[youngest] : committed_tag;
  wire bypass = complete && tags[completion_index] == expected_tag;
  wire expected_ready = count == 0 || written[youngest] || bypass;
  wire expected_value = bypass ? completion_value : count != 0 ? values[youngest] : committed_value;
  wire [3:0] checkpoints_used;
  ApeRename dut (
    .io_clear(clear), .io_argument(64'b0),
    .io_source_0(5'd10), .io_source_1(5'd0), .io_sourceUsed(2'b01),
    .io_sourceTag_0(source_tag), .io_sourceTag_1(source_zero), .io_sourceReady(source_ready),
    .io_sourceValue_0(source_value), .io_sourceValue_1(zero_value),
    .io_allocate_valid(allocate), .io_allocate_ready(allocate_ready),
    .io_allocate_payload(5'd10), .io_allocatedTag(allocated),
    .io_writeback_valid(complete), .io_writeback_payload_tag(tags[completion_index]),
    .io_writeback_payload_value({63'b0, completion_value}),
    .io_commit_valid(commit), .io_commit_payload_architectural(5'd10),
    .io_commit_payload_physical(tags[head]), .io_recover(recover),
    .io_checkpoint_valid(1'b0), .io_checkpoint_payload(3'b0),
    .io_resolve_valid(1'b0), .io_resolve_payload_slot(3'b0), .io_resolve_payload_redirect(1'b0),
    .io_squash(8'b0), .io_checkpointAvailable(), .io_checkpointsUsed(checkpoints_used),
    .io_committedArgument(argument), .io_freeCount(free_count), .clk(clk), .reset(reset)
  );
  always @* begin
    if ($initstate) assume(reset); else assume(!reset);
    if (reset || clear) assume(!allocate && !complete && !commit && !recover);
    if (complete) assume(live[completion_index] && !written[completion_index] && !recover);
    if (commit) assume(count != 0 && live[head] && written[head]);
  end

  reg saw_commit = 0, saw_recover = 0;
  always @(posedge clk) begin
    if (reset || clear) begin
      head <= 0; tail <= 0; count <= 0;
      live <= 0; written <= 0; values <= 0;
      committed_tag <= 10; committed_value <= 0;
      if (reset) begin saw_commit <= 0; saw_recover <= 0; end
    end else begin
      if (complete) begin
        written[completion_index] <= 1;
        values[completion_index] <= completion_value;
      end
      if (commit) begin
        committed_tag <= tags[head]; committed_value <= values[head];
        live[head] <= 0; head <= head + 1'b1;
        saw_commit <= 1;
      end
      if (allocation) begin
        live[tail] <= 1; written[tail] <= 0;
        tags[tail] <= allocated; tail <= tail + 1'b1;
      end
      count <= count + allocation - commit;
      if (recover) begin
        live <= 0; written <= 0; head <= 0; tail <= 0; count <= 0;
        saw_recover <= 1;
      end
    end
    if (!reset) begin
      assert(count <= 4);
      assert(free_count == 4 - count);
      assert(allocate_ready == (count < 4 && !clear && !recover));
      assert(source_tag == expected_tag);
      assert(source_ready[0] == expected_ready);
      if (expected_ready) assert(source_value == {63'b0, expected_value});
      assert(argument == {63'b0, committed_value});
      assert(source_zero == 0 && source_ready[1] && zero_value == 0 && checkpoints_used == 0);
      if (allocation) begin
        assert(allocated > 0 && allocated < 36 && allocated != committed_tag);
        for (integer i = 0; i < 4; i = i + 1)
          if (live[i]) assert(allocated != tags[i]);
      end
      cover(count == 4 && allocate && !allocate_ready);
      cover(complete && completion_index != head && count > 1);
      cover(commit && allocation);
      cover(commit && recover && count > 1);
      cover(saw_recover && allocation);
      cover(saw_commit && clear);
`ifdef MUTATION
      if (count > 0) assert(free_count == 4);
`endif
    end
  end
endmodule
