# This file is part of MyPaint.
# Copyright (C) 2007-2008 by Martin Renold <martinxyz@gmx.ch>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

import layer
import helpers
from gettext import gettext as _

class CommandStack:
    def __init__(self):
        self.call_before_action = []
        self.stack_observers = []
        self.clear()

    def __repr__(self):
        return "<CommandStack\n  <Undo len=%d last3=%r>\n" \
                "  <Redo len=%d last3=%r> >" % (
                    len(self.undo_stack), self.undo_stack[-3:],
                    len(self.redo_stack), self.redo_stack[:3],  )

    def clear(self):
        self.undo_stack = []
        self.redo_stack = []
        self.notify_stack_observers()

    def do(self, command):
        for f in self.call_before_action: f()
        self.redo_stack = [] # discard
        command.redo()
        self.undo_stack.append(command)
        self.reduce_undo_history()
        self.notify_stack_observers()

    def undo(self):
        if not self.undo_stack: return
        for f in self.call_before_action: f()
        command = self.undo_stack.pop()
        command.undo()
        self.redo_stack.append(command)
        self.notify_stack_observers()
        return command

    def redo(self):
        if not self.redo_stack: return
        for f in self.call_before_action: f()
        command = self.redo_stack.pop()
        command.redo()
        self.undo_stack.append(command)
        self.notify_stack_observers()
        return command

    def reduce_undo_history(self):
        stack = self.undo_stack
        self.undo_stack = []
        steps = 0
        for item in reversed(stack):
            self.undo_stack.insert(0, item)
            if not item.automatic_undo:
                steps += 1
            if steps == 30: # and memory > ...
                break

    def get_last_command(self):
        if not self.undo_stack: return None
        return self.undo_stack[-1]

    def update_last_command(self, **kwargs):
        cmd = self.get_last_command()
        if cmd is None:
            return None
        cmd.update(**kwargs)
        self.notify_stack_observers() # the display_name may have changed
        return cmd

    def notify_stack_observers(self):
        for func in self.stack_observers:
            func(self)

class Action:
    """An undoable, redoable action.

    Base class for all undo/redoable actions. Subclasses must implement the
    undo and redo methods. They should have a reference to the document in 
    self.doc.

    """
    automatic_undo = False
    display_name = _("Unknown Action")

    def __repr__(self):
        return "<%s>" % (self.display_name,)


    def redo(self):
        """Callback used to perform, or re-perform the Action.
        """
        raise NotImplementedError


    def undo(self):
        """Callback used to un-perform an already performed Action.
        """
        raise NotImplementedError


    def update(self, **kwargs):
        """In-place update on the tip of the undo stack.

        This method should update the model in the way specified in `**kwargs`.
        The interpretation of arguments is left to the concrete implementation.

        Updating the top Action on the command stack is used to prevent
        situations where an undo() followed by a redo() would result in
        multiple sendings of GdkEvents by code designed to keep interface state
        in sync with the model.

        """

        # Updating is used in situations where only the user's final choice of
        # a state such as layer visibility matters in the command-stream.
        # Creating a nice workflow for the user by using `undo()` then `do()`
        # with a replacement Action can sometimes cause GtkAction and
        # command.Action flurries or loops across multiple GdkEvent callbacks.
        #
        # This can make coding difficult elsewhere. For example,
        # GtkToggleActions must be kept in in sync with undoable boolean model
        # state, but even when an interlock or check is coded, the fact that
        # processing happens in multiple GtkEvent handlers can result in,
        # essentially, a toggle action which turns itself off immediately after
        # being toggled on. See https://gna.org/bugs/?20096 for a concrete
        # example.

        raise NotImplementedError


    # Utility functions
    def _notify_canvas_observers(self, affected_layers):
        bbox = helpers.Rect()
        for layer in affected_layers:
            layer_bbox = layer.get_bbox()
            bbox.expandToIncludeRect(layer_bbox)
        for func in self.doc.canvas_observers:
            func(*bbox)

    def _notify_document_observers(self):
        self.doc.call_doc_observers()

class Stroke(Action):
    display_name = _("Painting")
    def __init__(self, doc, stroke, snapshot_before):
        """called only when the stroke was just completed and is now fully rendered"""
        self.doc = doc
        assert stroke.finished
        self.stroke = stroke # immutable; not used for drawing any more, just for inspection
        self.before = snapshot_before
        self.doc.layer.add_stroke(stroke, snapshot_before)
        # this snapshot will include the updated stroke list (modified by the line above)
        self.after = self.doc.layer.save_snapshot()
    def undo(self):
        self.doc.layer.load_snapshot(self.before)
    def redo(self):
        self.doc.layer.load_snapshot(self.after)

class ClearLayer(Action):
    display_name = _("Clear Layer")
    def __init__(self, doc):
        self.doc = doc
    def redo(self):
        self.before = self.doc.layer.save_snapshot()
        self.doc.layer.clear()
        self._notify_document_observers()
    def undo(self):
        self.doc.layer.load_snapshot(self.before)
        del self.before
        self._notify_document_observers()

class LoadLayer(Action):
    display_name = _("Load Layer")
    def __init__(self, doc, tiledsurface):
        self.doc = doc
        self.tiledsurface = tiledsurface
    def redo(self):
        layer = self.doc.layer
        self.before = layer.save_snapshot()
        layer.load_from_surface(self.tiledsurface)
    def undo(self):
        self.doc.layer.load_snapshot(self.before)
        del self.before

class MergeLayer(Action):
    """merge the current layer into dst"""
    display_name = _("Merge Layers")
    def __init__(self, doc, dst):
        self.doc = doc
        self.dst_layer = dst
        self.normalize_src = ConvertLayerToNormalMode(doc, doc.layer)
        self.normalize_dst = ConvertLayerToNormalMode(doc, self.dst_layer)
        self.remove_src = RemoveLayer(doc)
    def redo(self):
        self.normalize_src.redo()
        self.normalize_dst.redo()
        self.dst_before = self.dst_layer.save_snapshot()
        assert self.doc.layer is not self.dst_layer
        self.doc.layer.merge_into(self.dst_layer)
        self.remove_src.redo()
        self.select_dst = SelectLayer(self.doc, self.dst_layer)
        self.select_dst.redo()
        self._notify_document_observers()
    def undo(self):
        self.select_dst.undo()
        del self.select_dst
        self.remove_src.undo()
        self.dst_layer.load_snapshot(self.dst_before)
        del self.dst_before
        self.normalize_dst.undo()
        self.normalize_src.undo()
        self._notify_document_observers()

class ConvertLayerToNormalMode(Action):
    display_name = _("Convert Layer Mode")
    def __init__(self, doc, layer):
        self.doc = doc
        self.layer = layer
        self.set_normal_mode = SetLayerCompositeOp(doc, 'svg:src-over', layer)
        self.set_opacity = SetLayerOpacity(doc, 1.0, layer)
    def redo(self):
        self.before = self.layer.save_snapshot()
        prev = self.doc.layer
        self.doc.layer = self.layer
        get_bg = self.doc.get_rendered_image_behind_current_layer
        self.layer.convert_to_normal_mode(get_bg)
        self.doc.layer = prev
        self.set_normal_mode.redo()
        self.set_opacity.redo()
    def undo(self):
        self.set_opacity.undo()
        self.set_normal_mode.undo()
        self.layer.load_snapshot(self.before)
        del self.before

class AddLayer(Action):
    display_name = _("Add Layer")
    def __init__(self, doc, insert_idx=None, after=None, name='', stack=None):
        self.doc = doc
        if stack:
            self.stack = stack
        else:
            self.stack = self.doc.layers
        self.insert_idx = insert_idx
        if after:
            l_idx = after.get_index()
            self.insert_idx = l_idx + 1
            self.stack = after.parent
        self.layer = layer.Layer(name)
        self.layer.content_observers.append(self.doc.layer_modified_cb)
        self.layer.set_symmetry_axis(self.doc.get_symmetry_axis())
    def redo(self):
        self.stack.insert(self.insert_idx, self.layer)
        assert self.layer.parent is not None
        self.prev = self.doc.layer
        self.doc.layer = self.layer
        self._notify_document_observers()
    def undo(self):
        self.stack.remove(self.layer)
        self.doc.layer = self.prev
        self._notify_document_observers()

class AddGroup(Action):
    """Adds an empty group or wraps a layer inside a group
    """
    display_name = _("Add Group")
    def __init__(self, doc, lay=None, name='', stack=None, index=0):
        self.doc = doc
        self.layer = lay
        if stack is None and self.layer is None:
            self.layer = self.doc.layer
        if stack is None:
            self.stack = self.layer.parent
            self.index = self.layer.get_index()
        else:
            self.stack = stack
            self.index = index
        self.group = layer.LayerStack(doc, None, name)
        self.selected = False
        self.layer.content_observers.append(self.doc.layer_modified_cb)
    def redo(self):
        self.stack.insert(self.index, self.group)
        self.prev_selected = self.doc.layer
        self.doc.layer = self.group   #avoid having floating layer selected
        if self.layer is not None:
            self.stack.remove(self.layer)
            self.group.append(self.layer)
        self.doc.layer = self.prev_selected
        self._notify_document_observers()
    def undo(self):
        self.doc.layer = self.group  #avoid having floating layer selected
        if self.layer is not None:
            self.group.remove(self.layer)
            self.stack.insert(self.index, self.layer)
        self.doc.layer = self.prev_selected
        self.stack.remove(self.group)
        self._notify_document_observers()

class RemoveLayer(Action):
    """Removes a layer, replacing it with a new one if it was the last.
    """
    display_name = _("Remove Layer")
    def __init__(self, doc,layer=None):
        self.doc = doc
        self.layer = layer
        self.newlayer0 = None
    def redo(self):
        if not self.layer:
            self.layer = self.doc.layer
        self.stack = self.layer.parent
        self.idx = self.layer.get_index()
        self.stack.remove(self.layer)
        if len(self.doc.layers) == 0:
            if self.newlayer0 is None:
                ly = layer.Layer("")
                ly.content_observers.append(self.doc.layer_modified_cb)
                ly.set_symmetry_axis(self.doc.get_symmetry_axis())
                self.newlayer0 = ly
            self.doc.layers.append(self.newlayer0)
            self.doc.layer = self.newlayer0
            assert self.idx == 0
        else:
            self.doc.layer = self.doc.layers[0] #FIXME select proper layer
        self._notify_canvas_observers([self.layer])
        self._notify_document_observers()
    def undo(self):
        if self.newlayer0 is not None:
            self.newlayer0.parent.remove(self.newlayer0)
        self.stack.insert(self.idx, self.layer)
        self.doc.layer = self.layer
        self._notify_canvas_observers([self.layer])
        self._notify_document_observers()

class SelectLayer(Action):
    display_name = _("Select Layer")
    automatic_undo = True
    def __init__(self, doc, layer):
        self.doc = doc
        self.layer = layer
    def redo(self):
        #assert self.layer in self.doc.layers
        self.previous = self.doc.layer
        self.doc.layer = self.layer
        self._notify_document_observers()
    def undo(self):
        self.doc.layer = self.previous
        self._notify_document_observers()

class MoveLayer(Action):
    display_name = _("Move Layer on Canvas")
    # NOT "Move Layer" for now - old translatable string with different sense
    def __init__(self, doc, layer, dx, dy, ignore_first_redo=True):
        self.doc = doc
        self.layer = layer
        self.dx = dx
        self.dy = dy
        self.ignore_first_redo = ignore_first_redo
    def redo(self):
        if self.ignore_first_redo:
            # these are typically created interactively, after
            # the entire layer has been moved
            self.ignore_first_redo = False
        else:
            self.layer.translate(self.dx, self.dy)
        self._notify_canvas_observers([self.layer])
        self._notify_document_observers()
    def undo(self):
        self.layer.translate(-self.dx, -self.dy)
        self._notify_canvas_observers([self.layer])
        self._notify_document_observers()

class ReorderSingleLayer(Action):
    display_name = _("Reorder Layer in Stack")
    def __init__(self, doc, layer, new_idx, select_new=False, new_stack=None):
        self.doc = doc
        self.layer = layer
        self.new_idx = new_idx
        self.new_stack = new_stack
        self.select_new = select_new
    def redo(self):
        self.old_stack = self.layer.parent
        if not self.new_stack:
            self.new_stack = self.old_stack
        self.old_idx = self.old_stack.index(self.layer)
        self.old_stack.remove(self.layer)
        self.new_stack.insert(self.new_idx, self.layer)
        if self.select_new:
            self.was_selected = self.doc.layer
            self.doc.layer = self.layer
        self._notify_canvas_observers([self.layer])
        self._notify_document_observers()
    def undo(self):
        self.new_stack.remove(self.layer)
        self.old_stack.insert(self.old_idx, self.layer)
        if self.select_new:
            self.doc.layer = self.was_selected
            self.was_selected = None
        self._notify_canvas_observers([self.layer])
        self._notify_document_observers()

class DuplicateLayer(Action):
    display_name = _("Duplicate Layer")
    def __init__(self, doc, lay, name=''):
        self.doc = doc
        self.layer = lay
        snapshot = self.layer.save_snapshot()
        self.new_layer = layer.Layer(name)
        self.new_layer.load_snapshot(snapshot)
        self.new_layer.content_observers.append(self.doc.layer_modified_cb)
        self.new_layer.set_symmetry_axis(doc.get_symmetry_axis())
    def redo(self):
        self.layer.parent.insert(self.layer.get_index()+1, self.new_layer)
        self._notify_canvas_observers([self.new_layer])
        self._notify_document_observers()
    def undo(self):
        self.layer.parent.remove(self.new_layer)
        self._notify_canvas_observers([self.layer])
        self._notify_document_observers()

class ReorderLayers(Action):
    display_name = _("Reorder Layer Stack")
    def __init__(self, doc, new_order):
        self.doc = doc
        self.old_order = doc.layers[:]
        self.selection = self.old_order[doc.layer_idx]
        self.new_order = new_order
        for layer in new_order:
            assert layer in self.old_order
        assert len(self.old_order) == len(new_order)
    def redo(self):
        self.doc.layers[:] = self.new_order
        self.doc.layer_idx = self.doc.layers.index(self.selection)
        self._notify_canvas_observers(self.doc.layers)
        self._notify_document_observers()
    def undo(self):
        self.doc.layers[:] = self.old_order
        self.doc.layer_idx = self.doc.layers.index(self.selection)
        self._notify_canvas_observers(self.doc.layers)
        self._notify_document_observers()

class RenameLayer(Action):
    display_name = _("Rename Layer")
    def __init__(self, doc, name, layer):
        self.doc = doc
        self.new_name = name
        self.layer = layer
    def redo(self):
        self.old_name = self.layer.name
        self.layer.name = self.new_name
        self._notify_document_observers()
    def undo(self):
        self.layer.name = self.old_name
        self._notify_document_observers()

class SetLayerVisibility(Action):
    def __init__(self, doc, visible, layer):
        self.doc = doc
        self.new_visibility = visible
        self.layer = layer
    def redo(self):
        self.old_visibility = self.layer.visible
        self.layer.visible = self.new_visibility
        self._notify_canvas_observers([self.layer])
        self._notify_document_observers()
    def undo(self):
        self.layer.visible = self.old_visibility
        self._notify_canvas_observers([self.layer])
        self._notify_document_observers()
    def update(self, visible):
        self.layer.visible = visible
        self.new_visibility = visible
        self._notify_canvas_observers([self.layer])
        self._notify_document_observers()
    @property
    def display_name(self):
        if self.new_visibility:
            return _("Make Layer Visible")
        else:
            return _("Make Layer Invisible")

class SetLayerLocked (Action):
    def __init__(self, doc, locked, layer):
        self.doc = doc
        self.new_locked = locked
        self.layer = layer
    def redo(self):
        self.old_locked = self.layer.locked
        self.layer.locked = self.new_locked
        self._notify_canvas_observers([self.layer])
        self._notify_document_observers()
    def undo(self):
        self.layer.locked = self.old_locked
        self._notify_canvas_observers([self.layer])
        self._notify_document_observers()
    def update(self, locked):
        self.layer.locked = locked
        self.new_locked = locked
        self._notify_canvas_observers([self.layer])
        self._notify_document_observers()
    @property
    def display_name(self):
        if self.new_locked:
            return _("Lock Layer")
        else:
            return _("Unlock Layer")

class SetLayerOpacity(Action):
    display_name = _("Change Layer Visibility")
    def __init__(self, doc, opacity, layer=None):
        self.doc = doc
        self.new_opacity = opacity
        self.layer = layer
    def redo(self):
        if self.layer:
            l = self.layer
        else:
            l = self.doc.layer
        previous_effective_opacity = l.effective_opacity
        self.old_opacity = l.opacity
        l.opacity = self.new_opacity
        if l.effective_opacity != previous_effective_opacity:
            self._notify_canvas_observers([l])
        self._notify_document_observers()
    def undo(self):
        if self.layer:
            l = self.layer
        else:
            l = self.doc.layer
        previous_effective_opacity = l.effective_opacity
        l.opacity = self.old_opacity
        if l.effective_opacity != previous_effective_opacity:
            self._notify_canvas_observers([l])
        self._notify_document_observers()

class SetLayerCompositeOp(Action):
    display_name = _("Change Layer Blending Mode")
    def __init__(self, doc, compositeop, layer=None):
        self.doc = doc
        self.new_compositeop = compositeop
        self.layer = layer
    def redo(self):
        if self.layer:
            l = self.layer
        else:
            l = self.doc.layer
        self.old_compositeop = l.compositeop
        l.compositeop = self.new_compositeop
        self._notify_canvas_observers([l])
        self._notify_document_observers()
    def undo(self):
        if self.layer:
            l = self.layer
        else:
            l = self.doc.layer
        l.compositeop = self.old_compositeop
        self._notify_canvas_observers([l])
        self._notify_document_observers()

