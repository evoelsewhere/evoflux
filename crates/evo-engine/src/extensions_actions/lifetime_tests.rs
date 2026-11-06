use super::*;
use evo_ai::providers::faux::{FauxProvider, FauxScript};
use evo_harness::types::AgentHarnessOptions;
use serde_json::json;

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn expired_reverse_bindings_fail_closed_but_still_reclaim_their_children() {
    let (host, cell) = HarnessActionHost::new_empty(
        vec![],
        std::env::temp_dir(),
        Handle::current(),
        BTreeMap::new(),
        evo_extensions::ToolCallContext::default(),
    );
    assert!(host
        .get_execution_context(json!({}))
        .await
        .unwrap_err()
        .contains("before harness"));
    let provider = FauxProvider::new(
        FauxScript::new()
            .with_text("slow")
            .with_tokens_per_second(0.1),
    );
    let parent = AgentHarness::create(AgentHarnessOptions {
        model: provider.default_model().clone(),
        models: vec![provider],
        ..Default::default()
    })
    .await
    .unwrap();
    HarnessActionHost::set_harness(&cell, Arc::new(parent.clone()));
    assert!(host.get_execution_context(json!({})).await.is_ok());
    let child = host
        .child_agent(7, json!({"op":"start","task":"report"}))
        .await
        .unwrap();
    let id = &child["childId"];
    drop(parent);
    assert!(host
        .get_execution_context(json!({}))
        .await
        .unwrap_err()
        .contains("after harness"));
    assert!(host
        .child_agent(7, json!({"op":"start","task":"stale"}))
        .await
        .unwrap_err()
        .contains("after harness"));
    tokio::time::timeout(std::time::Duration::from_secs(3), async {
        loop {
            let value = host
                .child_agent(7, json!({"op":"poll","childId":id}))
                .await
                .unwrap();
            if value["status"] == "failed" {
                break;
            }
            tokio::time::sleep(std::time::Duration::from_millis(2)).await;
        }
    })
    .await
    .unwrap();
    assert!(host
        .child_agent(8, json!({"op":"dispose","childId":id}))
        .await
        .is_err());
    host.child_agent(7, json!({"op":"dispose","childId":id}))
        .await
        .unwrap();
    assert!(host
        .child_agent(7, json!({"op":"poll","childId":id}))
        .await
        .is_err());
}

/// `sendUserMessage` must honour `deliverAs`.
///
/// It used to always call `prompt_text(..)`: while running the lane is busy -> error -> and since this action blocks
/// until the whole turn finishes and the bridge only checks `dispatched`, nobody saw the error -> the message was silently lost;
/// steer / followUp / nextTurn all turned into "start a new turn" as well.
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn send_user_message_queues_while_the_lane_is_busy() {
    let (host, cell) = HarnessActionHost::new_empty(
        vec![],
        std::env::temp_dir(),
        Handle::current(),
        BTreeMap::new(),
        evo_extensions::ToolCallContext::default(),
    );
    // Slow stream: there is only a window to queue a message while it is running.
    let provider = FauxProvider::new(
        FauxScript::new()
            .with_text("slow")
            .with_tokens_per_second(0.5),
    );
    let harness = AgentHarness::create(AgentHarnessOptions {
        model: provider.default_model().clone(),
        models: vec![provider],
        ..Default::default()
    })
    .await
    .unwrap();
    HarnessActionHost::set_harness(&cell, Arc::new(harness.clone()));

    let lane = harness.lane("main");
    let running = tokio::spawn({
        let lane = lane.clone();
        async move { lane.prompt_text("go", Vec::new()).await }
    });
    // Wait until the run is actually accepted before sending the message.
    tokio::time::timeout(std::time::Duration::from_secs(5), async {
        loop {
            if harness
                .snapshot()
                .await
                .map(|s| s.active.is_some())
                .unwrap_or(false)
            {
                break;
            }
            tokio::time::sleep(std::time::Duration::from_millis(2)).await;
        }
    })
    .await
    .expect("the run must become active");

    let value = host
        .send_user_message(json!({"text": "steering message", "deliverAs": "steer"}))
        .await
        .expect("sending a message must not fail just because the lane is busy");
    assert_eq!(
        value["status"], "queued",
        "a message sent while running should be queued, not start a new turn or error: {value}"
    );

    // It really is in the queue (not swallowed).
    let queued = lane.clear_queue().await.unwrap();
    assert_eq!(
        queued
            .steering
            .iter()
            .map(|m| m.text.as_str())
            .collect::<Vec<_>>(),
        vec!["steering message"]
    );

    let _ = lane.abort().await;
    let _ = running.await;
}

/// Abort must **hand queued messages back to the caller**, each with its own images.
///
/// Queue `[text only][text+red image][text+blue image]`: the head has no image, so a flattened scheme would
/// attach a later image to the head -- the user sees the wrong text/image pairing, and so does the model.
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn each_queued_message_keeps_its_own_image() {
    let (host, cell) = HarnessActionHost::new_empty(
        vec![],
        std::env::temp_dir(),
        Handle::current(),
        BTreeMap::new(),
        evo_extensions::ToolCallContext::default(),
    );
    let provider = FauxProvider::new(FauxScript::new().with_text("ok"));
    let harness = AgentHarness::create(AgentHarnessOptions {
        model: provider.default_model().clone(),
        models: vec![provider],
        ..Default::default()
    })
    .await
    .unwrap();
    HarnessActionHost::set_harness(&cell, Arc::new(harness.clone()));

    // Two **different** valid 1x1 PNGs (red / blue). They must be real PNGs: `steer` goes through
    // `normalize_user_images`, and anything it cannot decode is replaced with placeholder text and the image dropped.
    let red = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4z8AAAAMBAQDJ/pLvAAAAAElFTkSuQmCC";
    let blue = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGNgYPgPAAEDAQAIicLsAAAAAElFTkSuQmCC";
    let image = |data: &str| evo_ai::types::ImageContent {
        kind: evo_ai::types::ImageContentType,
        data: data.into(),
        mime_type: "image/png".into(),
    };
    let text_block = |text: &str| {
        evo_ai::types::Content::Text(evo_ai::types::TextContent {
            kind: evo_ai::types::TextContentType,
            text: text.into(),
            text_signature: None,
        })
    };
    let with_image = |text: &str, data: &str| {
        evo_agent::AgentMessage::User(evo_ai::types::UserMessage::new(
            evo_ai::types::UserContent::Blocks(vec![
                text_block(text),
                evo_ai::types::Content::Image(image(data)),
            ]),
            0,
        ))
    };
    let text_only = |text: &str| {
        evo_agent::AgentMessage::User(evo_ai::types::UserMessage::new(
            evo_ai::types::UserContent::Text(text.into()),
            0,
        ))
    };

    let lane = harness.lane("main");
    lane.steer(text_only("text only")).await.unwrap();
    lane.steer(with_image("the red one", red)).await.unwrap();
    lane.follow_up(with_image("the blue one", blue))
        .await
        .unwrap();

    let value = host.abort(json!({})).await.unwrap();
    let steer = value["steer"].as_array().expect("steer is an array");
    assert_eq!(steer.len(), 2, "{value}");
    assert_eq!(steer[0]["text"], json!("text only"), "{value}");
    assert_eq!(
        steer[0]["images"],
        json!([]),
        "the head has no image and must not pick up another message's image: {value}"
    );
    assert_eq!(steer[1]["text"], json!("the red one"), "{value}");
    assert_eq!(
        steer[1]["images"][0]["data"],
        json!(red),
        "an image must stay with its own text: {value}"
    );

    let follow = value["followUp"].as_array().expect("followUp is an array");
    assert_eq!(follow.len(), 1, "{value}");
    assert_eq!(follow[0]["text"], json!("the blue one"), "{value}");
    assert_eq!(
        follow[0]["images"][0]["data"],
        json!(blue),
        "follow-up images must not be mixed up with steer images: {value}"
    );
}

/// Abort on an idle lane is an idempotent no-op; the queue is still handed back (with kinds unchanged).
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn abort_reclaims_on_an_idle_lane_and_keeps_queue_kinds() {
    let (host, cell) = HarnessActionHost::new_empty(
        vec![],
        std::env::temp_dir(),
        Handle::current(),
        BTreeMap::new(),
        evo_extensions::ToolCallContext::default(),
    );
    let provider = FauxProvider::new(FauxScript::new().with_text("ok"));
    let harness = AgentHarness::create(AgentHarnessOptions {
        model: provider.default_model().clone(),
        models: vec![provider],
        ..Default::default()
    })
    .await
    .unwrap();
    HarnessActionHost::set_harness(&cell, Arc::new(harness.clone()));

    let lane = harness.lane("main");
    let msg = |text: &str| {
        evo_agent::AgentMessage::User(evo_ai::types::UserMessage::new(
            evo_ai::types::UserContent::Text(text.into()),
            0,
        ))
    };
    lane.steer(msg("steered")).await.unwrap();
    lane.follow_up(msg("queued")).await.unwrap();

    let value = host.abort(json!({})).await.unwrap();
    assert_eq!(
        value["aborted"],
        json!(false),
        "an idle abort is a no-op, not an error"
    );
    assert_eq!(
        value["steer"],
        json!([{ "text": "steered", "images": [] }]),
        "{value}"
    );
    assert_eq!(
        value["followUp"],
        json!([{ "text": "queued", "images": [] }]),
        "if follow-up were restored as steer it would be delivered mid-turn: {value}"
    );
    // Handed over, not copied: a second call returns nothing.
    let again = host.abort(json!({})).await.unwrap();
    assert_eq!(again["steer"], json!([]));
    assert_eq!(again["followUp"], json!([]));
}
