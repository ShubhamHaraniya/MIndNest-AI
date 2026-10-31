"use client";

import { useCallback, useRef, useState, type DragEvent } from "react";

import { hasFiles } from "@/lib/assignments";

/** Drag-and-drop of files onto an area. `dragging` is true while files are held over it (text
 *  and links dragged around the page are ignored). The counter keeps it steady when the pointer
 *  moves across child elements. */
export function useFileDrop(onFiles: (files: File[]) => void, enabled = true) {
  const [dragging, setDragging] = useState(false);
  const depth = useRef(0);

  const onDragEnter = useCallback(
    (event: DragEvent) => {
      if (!enabled || !hasFiles(event)) return;
      event.preventDefault();
      depth.current += 1;
      setDragging(true);
    },
    [enabled],
  );
  const onDragOver = useCallback(
    (event: DragEvent) => {
      if (!enabled || !hasFiles(event)) return;
      event.preventDefault(); // without this the browser would open the file instead
      event.dataTransfer.dropEffect = "copy";
    },
    [enabled],
  );
  const onDragLeave = useCallback(
    (event: DragEvent) => {
      if (!enabled || !hasFiles(event)) return;
      depth.current = Math.max(0, depth.current - 1);
      if (depth.current === 0) setDragging(false);
    },
    [enabled],
  );
  const onDrop = useCallback(
    (event: DragEvent) => {
      if (!enabled || !hasFiles(event)) return;
      event.preventDefault();
      depth.current = 0;
      setDragging(false);
      const files = Array.from(event.dataTransfer.files);
      if (files.length > 0) onFiles(files);
    },
    [enabled, onFiles],
  );

  return { dragging, bind: { onDragEnter, onDragOver, onDragLeave, onDrop } };
}
