// Original component-level formal harness for generated ApeCheckpoints RTL.
// The driver supplies the actual RTL from the source-bound recovery gate.
// Eight slots, 36 physical tags; CAPACITY is 1 or 4.
module CheckpointFormal(input wire clk);
  parameter CAPACITY = 4;
  parameter WATCHED_REGISTER = 10;
  (* anyseq *) reg reset, clear, capture, resolve, redirect, allocate;
  (* anyseq *) reg [2:0] capture_slot, resolve_slot;
  (* anyseq *) reg [5:0] allocation_tag;
  (* anyseq *) reg [7:0] squash;
  (* anyseq *) reg [191:0] snapshot;
  (* anyconst *) reg [2:0] watched_slot;
  localparam [4:0] watched_register = WATCHED_REGISTER;
  (* anyconst *) reg [5:0] watched_tag;
  wire available;
  wire [3:0] occupied;
  wire [191:0] restored;
  wire [35:0] reclaimed;
  ApeCheckpoints dut (
    .io_snapshot_0(snapshot[0 +: 6]), .io_restored_0(restored[0 +: 6]),
    .io_snapshot_1(snapshot[6 +: 6]), .io_restored_1(restored[6 +: 6]),
    .io_snapshot_2(snapshot[12 +: 6]), .io_restored_2(restored[12 +: 6]),
    .io_snapshot_3(snapshot[18 +: 6]), .io_restored_3(restored[18 +: 6]),
    .io_snapshot_4(snapshot[24 +: 6]), .io_restored_4(restored[24 +: 6]),
    .io_snapshot_5(snapshot[30 +: 6]), .io_restored_5(restored[30 +: 6]),
    .io_snapshot_6(snapshot[36 +: 6]), .io_restored_6(restored[36 +: 6]),
    .io_snapshot_7(snapshot[42 +: 6]), .io_restored_7(restored[42 +: 6]),
    .io_snapshot_8(snapshot[48 +: 6]), .io_restored_8(restored[48 +: 6]),
    .io_snapshot_9(snapshot[54 +: 6]), .io_restored_9(restored[54 +: 6]),
    .io_snapshot_10(snapshot[60 +: 6]), .io_restored_10(restored[60 +: 6]),
    .io_snapshot_11(snapshot[66 +: 6]), .io_restored_11(restored[66 +: 6]),
    .io_snapshot_12(snapshot[72 +: 6]), .io_restored_12(restored[72 +: 6]),
    .io_snapshot_13(snapshot[78 +: 6]), .io_restored_13(restored[78 +: 6]),
    .io_snapshot_14(snapshot[84 +: 6]), .io_restored_14(restored[84 +: 6]),
    .io_snapshot_15(snapshot[90 +: 6]), .io_restored_15(restored[90 +: 6]),
    .io_snapshot_16(snapshot[96 +: 6]), .io_restored_16(restored[96 +: 6]),
    .io_snapshot_17(snapshot[102 +: 6]), .io_restored_17(restored[102 +: 6]),
    .io_snapshot_18(snapshot[108 +: 6]), .io_restored_18(restored[108 +: 6]),
    .io_snapshot_19(snapshot[114 +: 6]), .io_restored_19(restored[114 +: 6]),
    .io_snapshot_20(snapshot[120 +: 6]), .io_restored_20(restored[120 +: 6]),
    .io_snapshot_21(snapshot[126 +: 6]), .io_restored_21(restored[126 +: 6]),
    .io_snapshot_22(snapshot[132 +: 6]), .io_restored_22(restored[132 +: 6]),
    .io_snapshot_23(snapshot[138 +: 6]), .io_restored_23(restored[138 +: 6]),
    .io_snapshot_24(snapshot[144 +: 6]), .io_restored_24(restored[144 +: 6]),
    .io_snapshot_25(snapshot[150 +: 6]), .io_restored_25(restored[150 +: 6]),
    .io_snapshot_26(snapshot[156 +: 6]), .io_restored_26(restored[156 +: 6]),
    .io_snapshot_27(snapshot[162 +: 6]), .io_restored_27(restored[162 +: 6]),
    .io_snapshot_28(snapshot[168 +: 6]), .io_restored_28(restored[168 +: 6]),
    .io_snapshot_29(snapshot[174 +: 6]), .io_restored_29(restored[174 +: 6]),
    .io_snapshot_30(snapshot[180 +: 6]), .io_restored_30(restored[180 +: 6]),
    .io_snapshot_31(snapshot[186 +: 6]), .io_restored_31(restored[186 +: 6]),
    .io_clear(clear), .io_allocation_valid(allocate), .io_allocation_payload(allocation_tag),
    .io_capture_valid(capture), .io_capture_payload(capture_slot),
    .io_resolve_valid(resolve), .io_resolve_payload_slot(resolve_slot),
    .io_resolve_payload_redirect(redirect), .io_squash(squash),
    .io_available(available), .io_occupied(occupied), .io_reclaimed(reclaimed),
    .clk(clk), .reset(reset)
  );

  reg [7:0] owners = 0;
  reg [5:0] saved_value = 0;
  reg allocated_after_capture = 0;
  reg saw_capture = 0, saw_redirect = 0;
  integer count, slot;
  always @* begin
    count = 0;
    for (slot = 0; slot < 8; slot = slot + 1)
      count = count + owners[slot];
    assume(watched_tag > 0 && watched_tag < 36);
    if ($initstate) assume(reset);
    else assume(!reset);
    if (reset || clear) begin
      assume(!capture && !resolve && !allocate);
    end else begin
      if (capture) assume(count < CAPACITY && !owners[capture_slot]);
      if (resolve) assume(owners[resolve_slot]);
      if (resolve && redirect) assume(!capture && !allocate);
      if (allocate) assume(allocation_tag > 0 && allocation_tag < 36);
    end
  end

  always @(posedge clk) begin
    if (reset || clear) begin
      owners <= 0;
      if (reset) begin
        saved_value <= 0;
        allocated_after_capture <= 0;
        saw_capture <= 0;
        saw_redirect <= 0;
      end
    end else begin
      for (integer s = 0; s < 8; s = s + 1) begin
        if (resolve && (resolve_slot == s || (redirect && squash[s])))
          owners[s] <= 0;
        if (capture && capture_slot == s) owners[s] <= 1;
      end
      if (owners[watched_slot] && allocate && allocation_tag == watched_tag)
        allocated_after_capture <= 1;
      if (capture && capture_slot == watched_slot) begin
        saved_value <= snapshot[watched_register * 6 +: 6];
        allocated_after_capture <= 0;
        saw_capture <= 1;
      end
      if (resolve && redirect && resolve_slot == watched_slot) saw_redirect <= 1;
    end
    if (!reset) begin
      assert(occupied == count);
      assert(available == (count < CAPACITY && !clear));
      if (owners[watched_slot] && resolve_slot == watched_slot) begin
        assert(restored[watched_register * 6 +: 6] == saved_value);
        assert(reclaimed[watched_tag] == allocated_after_capture);
      end
      cover(occupied == CAPACITY);
      cover(resolve && redirect && resolve_slot == watched_slot && allocated_after_capture);
      cover(saw_redirect && capture && capture_slot == watched_slot);
      cover(saw_capture && clear);
      if (CAPACITY > 1) cover(resolve && !redirect && capture);
`ifdef MUTATION
      // Deliberately false check: proves the negative control reaches live state.
      if (count > 0) assert(occupied == 0);
`endif
    end
  end
endmodule
