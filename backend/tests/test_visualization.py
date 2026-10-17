"""
Tests for the Visualization Script Engine and Flashcard Deck endpoints.
"""
import asyncio
import pytest


def test_generate_visualization_script(app):
    response = asyncio.run(app.generate_visualization_script(topic="Type 2 Diabetes", level=app.Level.high_school))
    assert response.topic == "Type 2 Diabetes"
    assert response.scene_type == "glut4_translocation_failure"
    assert len(response.keyframes) == 5
    assert response.keyframes[0].step == 1
    assert response.keyframes[0].target_object == "cell"


def test_generate_visualization_script_covid(app):
    response = asyncio.run(app.generate_visualization_script(topic="COVID-19 Virus", level=app.Level.college))
    assert response.topic == "COVID-19 Virus"
    assert response.scene_type == "viral_spike_fusion"
    assert response.keyframes[1].title == "ACE2 Receptor Docking"


def test_get_topic_flashcards(app):
    response = asyncio.run(app.get_topic_flashcards(topic="Diabetes"))
    assert response.topic == "Diabetes"
    assert response.cards_count == 3
    assert len(response.flashcards) == 3
    assert response.flashcards[0].front_prompt != ""
