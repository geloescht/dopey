# This file is part of MyPaint.
# Copyright (C) 2007-2008 by Martin Renold <martinxyz@gmx.ch>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

from command import Action, SelectLayer
import layer
from framelist import FrameList

def layername_from_description(description):
    layername = "CEL"
    if description != '':
        layername += " " + description
    return layername


class CreateTrack(Action):
    def __init__(self, doc, name=''):
        self.doc = doc
        self.frames = FrameList(24, self.doc.ani.opacities, name=name)
        self.group = layer.LayerStack(self.doc, None, name)
    
    def redo(self):
        self.doc.layers.append(self.group)
        self.doc.ani.tracks.append(self.frames)
        self.doc.call_doc_observers(("trackinserted", self.frames))
    
    def undo(self):
        self.doc.layers.remove(self.group)
        self.doc.ani.tracks.remove(self.frames)
        self.doc.call_doc_observers(("trackremoved", self.frames))

class SelectTrack(Action):
    def __init__(self, doc, track):
        self.doc = doc
        self.track = track
    
    def redo(self):
        self.prev = self.doc.ani.frames
        self.doc.ani.frames = self.track
        self.track_idx = self.track.idx
        self.track.select(self.prev.idx)
        self.doc.ani.update_opacities()
        self._notify_document_observers()
    
    def undo(self):
        self.doc.ani.frames = self.prev
        self.track.idx = self.track_idx
        self.doc.ani.update_opacities()
        self._notify_document_observers()

class SelectFrame(Action):
    def __init__(self, doc, idx):
        self.doc = doc
        self.frames = doc.ani.frames
        self.idx = idx
        self.prev_layer = None

    def redo(self):
        cel = self.frames.cel_at(self.idx)
        if cel is not None:
            # Select the corresponding layer:
            self.prev_layer = self.doc.layer
            self.doc.layer = cel
        
        self.prev_frame_idx = self.frames.idx
        self.frames.select(self.idx)
        self.doc.ani.update_opacities()
        self._notify_document_observers()
    
    def undo(self):
        if self.prev_layer is not None:
            self.doc.layer = self.prev_layer
        
        self.frames.select(self.prev_frame_idx)
        self.doc.ani.update_opacities()
        self._notify_document_observers()


class ToggleKey(Action):
    def __init__(self, doc, frame):
        self.doc = doc
        self.frame = frame
    
    def redo(self):
        self.prev_value = self.frame.is_key
        self.frame.toggle_key()
        self.doc.ani.update_opacities()
        self._notify_document_observers()

    def undo(self):
        self.frame.is_key = self.prev_value
        self.doc.ani.update_opacities()
        self._notify_document_observers()


class ToggleSkipVisible(Action):
    def __init__(self, doc, frame):
        self.doc = doc
        self.frame = frame

    def redo(self):
        self.prev_value = self.frame.skip_visible
        self.frame.toggle_skip_visible()
        self.doc.ani.update_opacities()
        self._notify_document_observers()

    def undo(self):
        self.frame.skip_visible = self.prev_value
        self.doc.ani.update_opacities()
        self._notify_document_observers()


class ChangeDescription(Action):
    def __init__(self, doc, frame, new_description):
        self.doc = doc
        self.frame = frame
        self.new_description = new_description
        if self.frame.cel != None:
            self.old_layername = self.frame.cel.name

    def redo(self):
        self.prev_value = self.frame.description
        self.frame.description = self.new_description
        self._notify_document_observers()
        if self.frame.cel != None:
            layername = layername_from_description(self.frame.description)
            self.frame.cel.name = layername

    def undo(self):
        self.frame.description = self.prev_value
        self._notify_document_observers()
        if self.frame.cel != None:
            self.frame.cel.name = self.old_layername


class AddCel(Action):
    def __init__(self, doc, frame):
        self.doc = doc
        self.frame = frame

        # Create new layer:
        layername = layername_from_description(self.frame.description)
        self.layer = layer.Layer(name=layername)
        self.layer._surface.observers.append(self.doc.layer_modified_cb)
    
    def redo(self):
        self.doc.layers.append(self.layer)
        self.prev = self.doc.layer
        self.doc.layer = self.layer
        
        self.frame.add_cel(self.layer)
        self._notify_canvas_observers([self.layer])
        self.doc.ani.update_opacities()
        self._notify_document_observers()
    
    def undo(self):
        self.doc.layers.remove(self.layer)
        self.doc.layer = self.prev
        self.frame.remove_cel()
        self._notify_canvas_observers([self.layer])
        self.doc.ani.update_opacities()
        self._notify_document_observers()


class RemoveCel(Action):
    def __init__(self, doc, frame):
        self.doc = doc
        self.frame = frame
        self.layer = self.frame.cel
        self.prev = None
        self.last = False
    
    def redo(self):
        num = self.doc.ani.frames.count_cel(self.layer)
        if num == 1:
            self.doc.layers.remove(self.layer)
            self.last = True
            self._notify_canvas_observers([self.layer])

        self.frame.remove_cel()
        
        if self.layer == self.doc.layer: #removing currently selected CEL
            self.prev = self.doc.layer
            self.doc.layer = self.doc.ani.frames.cel_for_frame(self.frame)

        self.doc.ani.update_opacities()
        self._notify_document_observers()
    
    def undo(self):
        if self.last:
            self.doc.layers.append(self.layer)
            self._notify_canvas_observers([self.layer])
        
        if self.prev is not None:
            self.doc.layer = self.prev
        self.frame.add_cel(self.layer)

        self.doc.ani.update_opacities()
        self._notify_document_observers()


class AppendFrames(Action):
    def __init__(self, doc, length):
        self.doc = doc
        self.frames = doc.ani.frames
        self.length = length

    def redo(self):
        self.frames.append_frames(self.length)
        self.doc.ani.cleared = True
        self._notify_document_observers()

    def undo(self):
        self.frames.remove_frames(self.length)
        self.doc.ani.cleared = True
        self._notify_document_observers()


class InsertFrames(Action):
    def __init__(self, doc, length):
        self.doc = doc
        self.frames = doc.ani.frames
        self.idx = doc.ani.frames.idx
        self.length = length

    def redo(self):
        self.frames.insert_empty_frames(self.length)
        self.doc.ani.cleared = True
        self._notify_document_observers()

    def undo(self):
        self.frames.remove_frames(self.length)
        self.doc.ani.cleared = True
        self._notify_document_observers()


class RemoveFrames(Action):
    def __init__(self, doc, length):
        self.doc = doc
        self.frames = doc.ani.frames
        self.idx = doc.ani.frames.idx
        self.length = length
        self.frames_to_remove = self.frames.frames_to_remove(self.length)
    
    def redo(self):
        for frame in self.frames_to_remove:
            if frame.cel is not None and \
            self.doc.ani.frames.count_cel(frame.cel) == 1:
                self.doc.layers.remove(frame.cel)
                self.doc.layer_idx = len(self.doc.layers) - 1
                self._notify_canvas_observers(frame.cel)

        self.frames.remove_frames(self.length)

        self.doc.ani.cleared = True
        self._notify_document_observers()
        
    def undo(self):
        for frame in self.frames_to_remove:
            if frame.cel is not None and \
            self.doc.ani.frames.count_cel(frame.cel) == 0:
                self.doc.layers.append(frame.cel)
                self._notify_canvas_observers([frame.cel])

        self.frames.insert_frames(self.frames_to_remove)

        self.doc.ani.cleared = True
        self._notify_document_observers()


class PasteCel(Action):
    def __init__(self, doc, frame):
        self.doc = doc
        self.frame = frame

    def redo(self):
        self.prev_edit_operation = self.doc.ani.edit_operation
        self.prev_edit_frame = self.doc.ani.edit_frame
        self.prev_cel = self.frame.cel

        if self.doc.ani.edit_operation == 'copy':
            # TODO duplicate layer?
            self.frame.add_cel(self.doc.ani.edit_frame.cel)
        elif self.doc.ani.edit_operation == 'cut':
            self.frame.add_cel(self.doc.ani.edit_frame.cel)
            self.doc.ani.edit_frame.remove_cel()
        else:
            raise Exception 

        self.doc.ani.edit_operation = None
        self.doc.ani.edit_frame = None

        self.doc.ani.update_opacities()
        self._notify_document_observers()

    def undo(self):
        self.doc.ani.edit_operation = self.prev_edit_operation
        self.doc.ani.edit_frame = self.prev_edit_frame
        self.frame.add_cel(self.prev_cel)
        self.doc.ani.update_opacities()
        self._notify_document_observers()
