(() => {
  const wsBase = `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}`;
  const rtcConfig = {
    iceServers: [{ urls: "stun:stun.l.google.com:19302" }]
  };

  const publisher = document.querySelector("[data-live-publisher]");
  if (publisher) {
    const token = publisher.dataset.token;
    const startButton = publisher.querySelector("[data-start-share]");
    const stopButton = publisher.querySelector("[data-stop-share]");
    const preview = publisher.querySelector("[data-publish-preview]");
    const status = publisher.querySelector("[data-publish-status]");
    let stream = null;
    let socket = null;
    const peers = new Map();

    const setStatus = (text) => { if (status) status.textContent = text; };

    const closePeer = (viewerId) => {
      const pc = peers.get(viewerId);
      if (pc) pc.close();
      peers.delete(viewerId);
    };

    async function createOffer(viewerId) {
      if (!stream || !socket || socket.readyState !== WebSocket.OPEN) return;
      closePeer(viewerId);
      const pc = new RTCPeerConnection(rtcConfig);
      peers.set(viewerId, pc);
      stream.getTracks().forEach((track) => pc.addTrack(track, stream));
      pc.onicecandidate = (event) => {
        if (event.candidate && socket.readyState === WebSocket.OPEN) {
          socket.send(JSON.stringify({
            type: "ice",
            viewer_id: viewerId,
            candidate: event.candidate
          }));
        }
      };
      const offer = await pc.createOffer();
      await pc.setLocalDescription(offer);
      socket.send(JSON.stringify({
        type: "offer",
        viewer_id: viewerId,
        sdp: pc.localDescription
      }));
    }

    async function start() {
      if (stream) return;
      try {
        stream = await navigator.mediaDevices.getDisplayMedia({
          video: { frameRate: { ideal: 30, max: 60 } },
          audio: false
        });
      } catch (error) {
        setStatus("Partage annulé ou refusé par le navigateur.");
        return;
      }

      preview.srcObject = stream;
      startButton.disabled = true;
      stopButton.disabled = false;
      setStatus("🔴 Diffusion active. Tu peux arrêter à tout moment.");

      socket = new WebSocket(`${wsBase}/ws/live/publish/${encodeURIComponent(token)}`);
      socket.addEventListener("message", async (event) => {
        const data = JSON.parse(event.data);
        if (data.type === "viewer_join") {
          await createOffer(data.viewer_id);
        } else if (data.type === "viewer_leave") {
          closePeer(data.viewer_id);
        } else if (data.type === "answer") {
          const pc = peers.get(data.viewer_id);
          if (pc && data.sdp) {
            await pc.setRemoteDescription(data.sdp);
          }
        } else if (data.type === "ice") {
          const pc = peers.get(data.viewer_id);
          if (pc && data.candidate) {
            try { await pc.addIceCandidate(data.candidate); } catch (_) {}
          }
        }
      });

      stream.getVideoTracks()[0]?.addEventListener("ended", stop);
    }

    function stop() {
      peers.forEach((pc) => pc.close());
      peers.clear();
      if (socket) socket.close();
      socket = null;
      if (stream) stream.getTracks().forEach((track) => track.stop());
      stream = null;
      preview.srcObject = null;
      startButton.disabled = false;
      stopButton.disabled = true;
      setStatus("Diffusion arrêtée.");
    }

    startButton?.addEventListener("click", start);
    stopButton?.addEventListener("click", stop);
    window.addEventListener("beforeunload", stop);
  }

  const viewer = document.querySelector("[data-live-viewer]");
  if (viewer) {
    const kind = viewer.dataset.kind;
    const matchId = viewer.dataset.matchId;

    [1, 2].forEach((slot) => {
      const video = viewer.querySelector(`[data-live-video="${slot}"]`);
      const placeholder = viewer.querySelector(`[data-live-placeholder="${slot}"]`);
      const socket = new WebSocket(
        `${wsBase}/ws/live/watch/${kind}/${matchId}/${slot}`
      );
      let pc = null;

      function ensurePeer() {
        if (pc) return pc;
        pc = new RTCPeerConnection(rtcConfig);
        pc.ontrack = (event) => {
          if (video) {
            video.srcObject = event.streams[0];
            video.muted = true;
          }
          if (placeholder) placeholder.style.display = "none";
        };
        pc.onicecandidate = (event) => {
          if (event.candidate && socket.readyState === WebSocket.OPEN) {
            socket.send(JSON.stringify({
              type: "ice",
              candidate: event.candidate
            }));
          }
        };
        return pc;
      }

      socket.addEventListener("message", async (event) => {
        const data = JSON.parse(event.data);
        if (data.type === "offer" && data.sdp) {
          const peer = ensurePeer();
          await peer.setRemoteDescription(data.sdp);
          const answer = await peer.createAnswer();
          await peer.setLocalDescription(answer);
          socket.send(JSON.stringify({
            type: "answer",
            sdp: peer.localDescription
          }));
        } else if (data.type === "ice" && data.candidate) {
          const peer = ensurePeer();
          try { await peer.addIceCandidate(data.candidate); } catch (_) {}
        }
      });

      socket.addEventListener("close", () => {
        if (pc) pc.close();
      });
    });
  }
})();
